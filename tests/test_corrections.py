from datetime import datetime, timezone

import pytest


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register", json={"name": "Farmer", "email": email, "password": "correcthorse"}
    )
    return response.json()["accessToken"]


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
