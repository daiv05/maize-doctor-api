from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter
from app.routers import auth, contributions, corrections

app = FastAPI(title="maize-doctor-api")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth.router)
app.include_router(corrections.router)
app.include_router(contributions.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
