import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.rate_limit import limiter
from app.db import get_db
from app.main import app
from app.models import app_release, contribution, correction, user  # noqa: F401
from app.models.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]

test_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)


def _alembic_config() -> Config:
    """
    Builds an Alembic config bound to the test database.

    @returns {Config} Config with absolute paths, usable from any working directory.
    """
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database() -> AsyncIterator[None]:
    """
    Builds the test schema by running the real Alembic migrations, so any drift
    between the models and the migration files fails here instead of at deploy
    time. Alembic's env.py drives its own event loop via asyncio.run(), which
    cannot nest inside the running test loop - hence the worker thread. The
    pre-drop clears any schema left behind by an interrupted or pre-Alembic run,
    which would otherwise make `upgrade head` fail on already-existing tables.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    yield
    await asyncio.to_thread(command.downgrade, _alembic_config(), "base")
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    connection = await test_engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = override_get_db

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    limiter.reset()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
