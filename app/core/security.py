import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """
    Normalizes a client-supplied timestamp for storage in a naive DateTime column.

    @param {datetime} value Aware or naive timestamp; naive values are assumed UTC.
    @returns {datetime} Equivalent instant expressed as naive UTC.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str) -> str:
    expire = utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    expire = utcnow() + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": user_id, "type": "refresh", "exp": expire, "jti": uuid.uuid4().hex}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
