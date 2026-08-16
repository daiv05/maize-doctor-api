import pytest
from fastapi import HTTPException, status

from app.core.deps import get_current_user


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
