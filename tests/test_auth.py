import pytest


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
