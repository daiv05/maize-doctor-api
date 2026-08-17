import asyncio
import io
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.rate_limit import limiter
from app.db import get_db
from app.main import app
from app.models.contribution import DatasetContribution
from app.models.user import RefreshToken, User
from tests.conftest import test_engine


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register", json={"name": "Farmer", "email": email, "password": "correcthorse"}
    )
    return response.json()["accessToken"]


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buffer, format="PNG")
    return buffer.getvalue()


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
        user_id = await cleanup_session.scalar(select(User.id).where(User.email == "racer-contrib@example.com"))
        await cleanup_session.execute(delete(DatasetContribution).where(DatasetContribution.client_id == "race-1"))
        if user_id is not None:
            await cleanup_session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
            await cleanup_session.execute(delete(User).where(User.id == user_id))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_create_contribution_requires_auth(client):
    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-1",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_contribution_returns_201(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower1@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-1",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["label"] == "common_rust"


@pytest.mark.asyncio
async def test_replaying_same_client_id_is_idempotent(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower2@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "clientId": "local-2",
        "label": "gray_leaf_spot",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    files = {"image": ("leaf.png", _png_bytes(), "image/png")}

    first = await client.post("/dataset-contributions", data=data, files=files, headers=headers)
    second = await client.post("/dataset-contributions", data=data, files=files, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_corrupt_image_returns_422(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower3@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-3",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("broken.png", b"not a real image", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_over_length_note_returns_422(client, tmp_path, monkeypatch):
    """`note` is String(1000); MySQL runs STRICT_TRANS_TABLES, so an unvalidated
    over-length value used to raise DataError and surface as a 500."""
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower4@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-4",
            "label": "common_rust",
            "note": "x" * 1500,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_concurrent_same_client_id_race_recovers_via_integrity_error(race_client, tmp_path, monkeypatch):
    """
    Deterministically reproduces the check-then-act race: two requests with the
    same (user_id, client_id) both pass the "not found" SELECT before either
    commits, so the second INSERT hits the unique constraint. Patches
    AsyncSession.commit so the first of the two concurrent commits blocks until
    the second one has fully succeeded, guaranteeing the collision instead of
    relying on incidental asyncio scheduling.
    """
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))

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

    token = await _register_and_get_token(race_client, "racer-contrib@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "clientId": "race-1",
        "label": "common_rust",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }

    monkeypatch.setattr(AsyncSession, "commit", patched_commit)

    responses = await asyncio.gather(
        race_client.post(
            "/dataset-contributions",
            data=data,
            files={"image": ("leaf.png", _png_bytes(), "image/png")},
            headers=headers,
        ),
        race_client.post(
            "/dataset-contributions",
            data=data,
            files={"image": ("leaf.png", _png_bytes(), "image/png")},
            headers=headers,
        ),
    )

    assert call_count["n"] == 2
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
