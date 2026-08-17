from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter
from app.routers import app_version, auth, contributions, corrections

app = FastAPI(title="maize-doctor-api")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Keeps unhandled failures on the API's `{"detail": ...}` JSON contract."""
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(auth.router)
app.include_router(corrections.router)
app.include_router(contributions.router)
app.include_router(app_version.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
