import pytest


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_five_requests_per_minute(client):
    payload = {"email": "nope@example.com", "password": "wrong"}

    responses = [await client.post("/auth/login", json=payload) for _ in range(6)]

    assert responses[-1].status_code == 429
    assert any(r.status_code == 401 for r in responses[:5])
