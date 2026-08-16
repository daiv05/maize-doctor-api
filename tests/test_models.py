import pytest
from sqlalchemy import select

from app.models.user import User


@pytest.mark.asyncio
async def test_create_and_read_user(db_session):
    user = User(name="Ana", email="ana@example.com", password_hash="hashed")
    db_session.add(user)
    await db_session.commit()

    result = await db_session.scalar(select(User).where(User.email == "ana@example.com"))

    assert result is not None
    assert result.name == "Ana"
