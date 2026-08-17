from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import limiter
from app.db import get_db
from app.main import app


@pytest_asyncio.fixture
async def failing_db_client() -> AsyncIterator[AsyncClient]:
    """
    Client wired to a `get_db` that blows up with an unexpected (non-HTTP)
    exception, so a real endpoint fails the way a genuine outage would. Starlette
    re-raises after the error response is sent, hence `raise_app_exceptions=False`.
    """

    async def failing_get_db() -> AsyncIterator[None]:
        raise RuntimeError("database exploded")
        yield  # pragma: no cover - unreachable, keeps this an async generator

    limiter.reset()
    app.dependency_overrides[get_db] = failing_get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_unhandled_exception_returns_json_detail(failing_db_client):
    response = await failing_db_client.post(
        "/auth/login", json={"email": "ana@example.com", "password": "s3cret!"}
    )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "Internal server error"}
