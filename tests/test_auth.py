import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.db import get_db
from app.main import app
from app.models.user import RefreshToken, User
from tests.conftest import test_engine

RACE_EMAIL = "racer-register@example.com"


@pytest_asyncio.fixture
async def race_client() -> AsyncIterator[AsyncClient]:
    """
    Client whose requests each get their own DB session/connection, unlike the
    `client` fixture (single shared session), so two requests issued concurrently
    via asyncio.gather are genuinely independent transactions against MySQL -
    required to reproduce the check-then-act duplicate-email race.
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
        user_id = await cleanup_session.scalar(select(User.id).where(User.email == RACE_EMAIL))
        if user_id is not None:
            await cleanup_session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
            await cleanup_session.execute(delete(User).where(User.id == user_id))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_get_current_user_with_no_credentials_returns_401():
    """Test that missing Authorization header raises 401, not 403."""
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None, db=None)

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Not authenticated"


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_tokens(client):
    response = await client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": "s3cret!"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["accessToken"]
    assert body["refreshToken"]


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client):
    payload = {"name": "Ana", "email": "dup@example.com", "password": "s3cret!"}
    await client.post("/auth/register", json=payload)

    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_same_email_race_returns_409_not_500(race_client, monkeypatch):
    """
    Deterministically reproduces the check-then-act race: two registrations for
    the same email both pass the "not found" SELECT, so the second INSERT hits
    the unique index on users.email. Gates `AsyncSession.flush` rather than
    `commit` (as the corrections race test does) because register's INSERT is
    emitted at the explicit flush, not at commit time: gating commit would leave
    the second request blocked on the first one's uncommitted row lock.
    """
    original_flush = AsyncSession.flush
    gate = asyncio.Event()
    call_count = {"n": 0}

    async def patched_flush(self, *args, **kwargs):
        call_count["n"] += 1
        this_call = call_count["n"]
        if this_call == 1:
            await gate.wait()
            return await original_flush(self, *args, **kwargs)
        result = await original_flush(self, *args, **kwargs)
        gate.set()
        return result

    payload = {"name": "Racer", "email": RACE_EMAIL, "password": "correcthorse"}
    monkeypatch.setattr(AsyncSession, "flush", patched_flush)

    responses = await asyncio.gather(
        race_client.post("/auth/register", json=payload),
        race_client.post("/auth/register", json=payload),
    )

    assert call_count["n"] == 2
    assert sorted(response.status_code for response in responses) == [201, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json() == {"detail": "Email already registered"}


@pytest.mark.asyncio
async def test_login_with_correct_credentials_returns_tokens(client):
    await client.post(
        "/auth/register",
        json={"name": "Beto", "email": "beto@example.com", "password": "correcthorse"},
    )

    response = await client.post(
        "/auth/login", json={"email": "beto@example.com", "password": "correcthorse"}
    )

    assert response.status_code == 200
    assert response.json()["accessToken"]


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(client):
    await client.post(
        "/auth/register",
        json={"name": "Beto", "email": "beto2@example.com", "password": "correcthorse"},
    )

    response = await client.post(
        "/auth/login", json={"email": "beto2@example.com", "password": "wrong"}
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_returns_new_token_pair(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Cora", "email": "cora@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]

    response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"]
    assert body["refreshToken"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_rejects_reused_token(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Dana", "email": "dana@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]
    await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Eli", "email": "eli@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]

    logout_response = await client.post("/auth/logout", json={"refreshToken": refresh_token})
    assert logout_response.status_code == 204

    reuse_response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})
    assert reuse_response.status_code == 401
