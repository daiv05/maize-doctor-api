import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.rate_limit import limiter
from app.db import get_db
from app.main import app
from app.models.correction import Correction
from app.models.user import RefreshToken, User
from tests.conftest import test_engine


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register", json={"name": "Farmer", "email": email, "password": "correcthorse"}
    )
    return response.json()["accessToken"]


@pytest_asyncio.fixture
async def race_client() -> AsyncIterator[AsyncClient]:
    """
    Client whose requests each get their own DB session/connection, unlike the
    `client` fixture (single shared session), so two requests issued concurrently
    via asyncio.gather are genuinely independent transactions against MySQL -
    required to reproduce the check-then-act idempotency race.
    """
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    limiter.reset()
    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    async with session_factory() as cleanup_session:
        user_id = await cleanup_session.scalar(select(User.id).where(User.email == "racer@example.com"))
        await cleanup_session.execute(delete(Correction).where(Correction.client_id == "race-1"))
        if user_id is not None:
            await cleanup_session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
            await cleanup_session.execute(delete(User).where(User.id == user_id))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_create_correction_requires_auth(client):
    response = await client.post(
        "/corrections",
        json={
            "clientId": "local-1",
            "scanId": "scan-1",
            "observedLabel": "common_rust",
            "note": None,
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_correction_returns_201(client):
    token = await _register_and_get_token(client, "farmer1@example.com")

    response = await client.post(
        "/corrections",
        json={
            "clientId": "local-1",
            "scanId": "scan-1",
            "observedLabel": "common_rust",
            "note": "leaf had visible pustules",
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["clientId"] == "local-1"


@pytest.mark.asyncio
async def test_replaying_same_client_id_is_idempotent(client):
    token = await _register_and_get_token(client, "farmer2@example.com")
    payload = {
        "clientId": "local-2",
        "scanId": "scan-2",
        "observedLabel": "gray_leaf_spot",
        "note": None,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/corrections", json=payload, headers=headers)
    second = await client.post("/corrections", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_concurrent_same_client_id_race_recovers_via_integrity_error(race_client, monkeypatch):
    """
    Deterministically reproduces the check-then-act race: two requests with the
    same (user_id, client_id) both pass the "not found" SELECT before either
    commits, so the second INSERT hits the unique constraint. Patches
    AsyncSession.commit so the first of the two concurrent commits blocks until
    the second one has fully succeeded, guaranteeing the collision instead of
    relying on incidental asyncio scheduling.
    """
    original_commit = AsyncSession.commit
    gate = asyncio.Event()
    call_count = {"n": 0}

    async def patched_commit(self, *args, **kwargs):
        call_count["n"] += 1
        this_call = call_count["n"]
        if this_call == 1:
            await gate.wait()
            return await original_commit(self, *args, **kwargs)
        result = await original_commit(self, *args, **kwargs)
        gate.set()
        return result

    token = await _register_and_get_token(race_client, "racer@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "clientId": "race-1",
        "scanId": "scan-race",
        "observedLabel": "common_rust",
        "note": None,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    monkeypatch.setattr(AsyncSession, "commit", patched_commit)

    responses = await asyncio.gather(
        race_client.post("/corrections", json=payload, headers=headers),
        race_client.post("/corrections", json=payload, headers=headers),
    )

    assert call_count["n"] == 2
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
