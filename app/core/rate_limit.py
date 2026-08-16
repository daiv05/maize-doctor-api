from fastapi import Request
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.security import decode_token

limiter = Limiter(key_func=get_remote_address)


def user_or_ip_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            return f"user:{payload['sub']}"
        except JWTError:
            pass
    return f"ip:{get_remote_address(request)}"
