import pytest
from sqlalchemy import text

from app.db import engine


@pytest.mark.asyncio
async def test_real_engine_serves_repeated_connections():
    """
    Guards against connection-argument regressions on the production engine
    (`app.db.engine`), which the rest of the suite never exercises because every
    test goes through conftest's `test_engine` override. `pool_pre_ping=True`
    used to make every pooled re-checkout raise TypeError from the aiomysql
    adapter's ping(), turning roughly half of all real requests into 500s.
    """
    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1

    async with engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
