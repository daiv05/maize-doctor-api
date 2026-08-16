import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_hash_token_is_deterministic():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("xyz")


def test_access_token_roundtrip():
    token = create_access_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    token, expires_at = create_refresh_token("user-123")
    payload = decode_token(token)
    assert payload["sub"] == "user-123"
    assert payload["type"] == "refresh"
    assert expires_at is not None


def test_decode_invalid_token_raises():
    with pytest.raises(JWTError):
        decode_token("not-a-real-token")
