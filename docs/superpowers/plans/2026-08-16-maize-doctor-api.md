# maize-doctor-api Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI backend that serves app-version checks and accepts `corrections`/`dataset-contributions` sync from the offline-first `maize-doctor-app`, per the approved design spec.

**Architecture:** FastAPI + SQLAlchemy 2.0 async ORM + Alembic migrations against MySQL, JWT auth (access + rotating refresh tokens), `slowapi` rate limiting, images stored on a local disk volume with PIL validation before acceptance. Every JSON request/response uses camelCase (via a shared Pydantic base model) to match the field names the app's `FastApiSyncClient.ts` already sends.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async, `aiomysql` driver), Alembic, MySQL 8, `python-jose`, `passlib[bcrypt]`, `slowapi`, Pillow, `pytest` + `pytest-asyncio` + `httpx`, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-16-maize-doctor-api-design.md`

## Global Constraints

- Scope is exactly: app-version check, `POST /corrections`, `POST /dataset-contributions`, plus the auth endpoints those two need. **No `/scans` endpoint.**
- All JSON field names are camelCase on the wire (`clientId`, `scanId`, `observedLabel`, `createdAt`, etc.) — this must match `maize-doctor-app/src/api/FastApiSyncClient.ts` exactly.
- `corrections` and `dataset-contributions` writes are idempotent on `(user_id, client_id)` — a retried POST with the same `clientId` returns the existing row with 200, never a duplicate or an error.
- Contributed images are validated with PIL before being written to disk; corrupt/non-image uploads get 422, oversized uploads get 413.
- No contribution-approval endpoints, no account lockout, no object storage, no separate model distribution — all explicitly out of scope per the spec.
- Rate limits (from the spec): `/auth/login` & `/auth/register` 5/min/IP, `/auth/refresh` 10/min/IP, `/corrections` & `/dataset-contributions` 30/min/user, `/app-version` 60/min/IP.
- Tests run against a real MySQL instance started via `docker compose`, not a mocked DB (project convention).

---

### Task 1: Project scaffolding, config, DB engine, health check

**Files:**
- Create: `maize-doctor-api/requirements.txt`
- Create: `maize-doctor-api/requirements-dev.txt`
- Create: `maize-doctor-api/Dockerfile`
- Create: `maize-doctor-api/docker-compose.yml`
- Create: `maize-doctor-api/docker/init-test-db.sql`
- Create: `maize-doctor-api/.env.example`
- Create: `maize-doctor-api/.gitignore`
- Create: `maize-doctor-api/app/__init__.py`
- Create: `maize-doctor-api/app/config.py`
- Create: `maize-doctor-api/app/db.py`
- Create: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_health.py`

**Interfaces:**
- Produces: `app.config.settings` (a `Settings` instance with `.database_url`, `.jwt_secret`, `.jwt_algorithm`, `.access_token_expire_minutes`, `.refresh_token_expire_days`, `.upload_dir`, `.max_upload_size_mb`), `app.db.get_db` (async generator FastAPI dependency yielding an `AsyncSession`), `app.main.app` (the `FastAPI` instance).

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
aiomysql==0.2.0
alembic==1.13.2
pydantic==2.9.2
pydantic-settings==2.5.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
slowapi==0.1.9
pillow==10.4.0
python-multipart==0.0.9
email-validator==2.2.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
.venv/
uploads/
```

- [ ] **Step 4: Create `.env.example`**

```
DATABASE_URL=mysql+aiomysql://root:root@localhost:3306/maize_doctor
JWT_SECRET=change-me-to-a-random-secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=30
UPLOAD_DIR=/data/uploads
MAX_UPLOAD_SIZE_MB=10
```

Copy it to `.env` for local dev: `cp .env.example .env`.

- [ ] **Step 5: Create `app/__init__.py`** (empty file, marks `app` as a package)

- [ ] **Step 6: Create `app/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    upload_dir: str = "/data/uploads"
    max_upload_size_mb: int = 10


settings = Settings()
```

- [ ] **Step 7: Create `app/db.py`**

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
```

- [ ] **Step 8: Create `app/main.py`**

```python
from fastapi import FastAPI

app = FastAPI(title="maize-doctor-api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 9: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 10: Create `docker/init-test-db.sql`**

```sql
CREATE DATABASE IF NOT EXISTS maize_doctor_test;
```

- [ ] **Step 11: Create `docker-compose.yml`**

```yaml
services:
  mysql:
    image: mysql:8.4
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: maize_doctor
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./docker/init-test-db.sql:/docker-entrypoint-initdb.d/init-test-db.sql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 5s
      retries: 10

  api:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      mysql:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - uploads:/data/uploads

volumes:
  mysql_data:
  uploads:
```

- [ ] **Step 12: Start MySQL and verify it's healthy**

Run: `cd maize-doctor-api && cp .env.example .env && docker compose up -d mysql`
Expected: `docker compose ps` shows `mysql` as `healthy` within ~15s.

- [ ] **Step 13: Create a Python virtualenv and install dependencies for local test runs**

Run:
```bash
cd maize-doctor-api
python -m venv .venv
.venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```
Expected: install completes without errors.

- [ ] **Step 14: Write the failing health-check test**

`tests/test_health.py`:
```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Also create `tests/__init__.py` (empty) and `pytest.ini` at the repo root:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 15: Run the test to verify it passes**

Run: `pytest tests/test_health.py -v`
Expected: PASS (this endpoint needs no DB, so it should pass immediately — this step confirms the project scaffolding/imports work end to end).

- [ ] **Step 16: Commit**

```bash
git add requirements.txt requirements-dev.txt Dockerfile docker-compose.yml docker/init-test-db.sql .env.example .gitignore app/__init__.py app/config.py app/db.py app/main.py tests/__init__.py tests/test_health.py pytest.ini
git commit -m "feat: scaffold FastAPI project with health check"
```

---

### Task 2: SQLAlchemy models, Alembic migrations, DB test fixtures

**Files:**
- Create: `maize-doctor-api/app/models/__init__.py`
- Create: `maize-doctor-api/app/models/base.py`
- Create: `maize-doctor-api/app/models/user.py`
- Create: `maize-doctor-api/app/models/correction.py`
- Create: `maize-doctor-api/app/models/contribution.py`
- Create: `maize-doctor-api/app/models/app_release.py`
- Create: `maize-doctor-api/alembic.ini`
- Create: `maize-doctor-api/alembic/env.py`
- Create: `maize-doctor-api/alembic/script.py.mako`
- Create: `maize-doctor-api/tests/conftest.py`
- Test: `maize-doctor-api/tests/test_models.py`

**Interfaces:**
- Consumes: `app.config.settings` (Task 1), `app.db.SessionLocal`/`get_db` (Task 1).
- Produces: `app.models.base.Base` (SQLAlchemy `DeclarativeBase`), ORM classes `User`, `RefreshToken` (`app.models.user`), `Correction` (`app.models.correction`), `DatasetContribution` (`app.models.contribution`), `AppRelease` (`app.models.app_release`) — exact columns below, used by every later task. Test fixtures `db_session` and `client` in `tests/conftest.py`, reused by all remaining test files.

- [ ] **Step 1: Create `app/models/__init__.py`** (empty)

- [ ] **Step 2: Create `app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

- [ ] **Step 3: Create `app/models/user.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 4: Create `app/models/correction.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Correction(Base):
    __tablename__ = "corrections"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_correction_user_client"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    observed_label: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 5: Create `app/models/contribution.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DatasetContribution(Base):
    __tablename__ = "dataset_contributions"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_contribution_user_client"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
```

- [ ] **Step 6: Create `app/models/app_release.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppRelease(Base):
    __tablename__ = "app_releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[str] = mapped_column(String(30), nullable=False)
    min_supported_version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    download_url: Mapped[str] = mapped_column(String(500), nullable=False)
    release_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
```

- [ ] **Step 7: Initialize Alembic and wire it to the async engine**

Run: `cd maize-doctor-api && alembic init alembic`

Then replace the generated `alembic/env.py` with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models import app_release, contribution, correction, user  # noqa: F401
from app.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = create_async_engine(settings.database_url)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

In `alembic.ini`, delete or comment out the `sqlalchemy.url = ...` line (the URL now comes from `app.config.settings` inside `env.py`).

- [ ] **Step 8: Generate and apply the initial migration**

Run:
```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
Expected: a new file appears under `alembic/versions/` creating `users`, `refresh_tokens`, `corrections`, `dataset_contributions`, `app_releases`; `alembic upgrade head` exits 0 and the tables exist in the `maize_doctor` database (verify with `docker compose exec mysql mysql -uroot -proot -e "SHOW TABLES IN maize_doctor;"`).

- [ ] **Step 9: Create `tests/conftest.py` with DB-backed test fixtures**

```python
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import settings
from app.db import get_db
from app.main import app
from app.models.base import Base

test_engine = create_async_engine(settings.database_url, echo=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database() -> AsyncIterator[None]:
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

Tests must point at the **test** database, not the dev one. Set this for every local test run:
`DATABASE_URL=mysql+aiomysql://root:root@localhost:3306/maize_doctor_test`

- [ ] **Step 10: Write the failing model round-trip test**

`tests/test_models.py`:
```python
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
```

- [ ] **Step 11: Run the test to verify it passes**

Run (PowerShell): `$env:DATABASE_URL="mysql+aiomysql://root:root@localhost:3306/maize_doctor_test"; pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add app/models alembic alembic.ini tests/conftest.py tests/test_models.py
git commit -m "feat: add SQLAlchemy models and Alembic migrations"
```

---

### Task 3: Security core (hashing, JWT) and rate-limit infrastructure

**Files:**
- Create: `maize-doctor-api/app/core/__init__.py`
- Create: `maize-doctor-api/app/core/security.py`
- Create: `maize-doctor-api/app/core/rate_limit.py`
- Modify: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_security.py`

**Interfaces:**
- Consumes: `app.config.settings` (Task 1).
- Produces: `app.core.security.utcnow() -> datetime`, `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, `hash_token(token: str) -> str`, `create_access_token(user_id: str) -> str`, `create_refresh_token(user_id: str) -> tuple[str, datetime]`, `decode_token(token: str) -> dict`. `app.core.rate_limit.limiter` (`slowapi.Limiter` instance) and `user_or_ip_key(request: Request) -> str`, used by every router task from here on.

- [ ] **Step 1: Create `app/core/__init__.py`** (empty)

- [ ] **Step 2: Write the failing security unit tests**

`tests/test_security.py`:
```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.security'`.

- [ ] **Step 4: Create `app/core/security.py`**

```python
import hashlib
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    payload = {"sub": user_id, "type": "refresh", "exp": expire}
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expire


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_security.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Create `app/core/rate_limit.py`**

```python
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
```

- [ ] **Step 7: Wire the limiter into the FastAPI app**

Modify `app/main.py` to:

```python
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.rate_limit import limiter

app = FastAPI(title="maize-doctor-api")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 8: Run the full test suite to confirm nothing broke**

Run: `pytest -v`
Expected: PASS (health, models, security tests all green).

- [ ] **Step 9: Commit**

```bash
git add app/core app/main.py tests/test_security.py
git commit -m "feat: add JWT/password security core and rate-limit infrastructure"
```

---

### Task 4: Auth register & login

**Files:**
- Create: `maize-doctor-api/app/schemas/__init__.py`
- Create: `maize-doctor-api/app/schemas/base.py`
- Create: `maize-doctor-api/app/schemas/auth.py`
- Create: `maize-doctor-api/app/routers/__init__.py`
- Create: `maize-doctor-api/app/routers/auth.py`
- Modify: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_auth.py`

**Interfaces:**
- Consumes: `app.db.get_db` (Task 1), `app.models.user.User`/`RefreshToken` (Task 2), `app.core.security.{hash_password,verify_password,create_access_token,create_refresh_token,hash_token}` (Task 3), `app.core.rate_limit.limiter` (Task 3).
- Produces: `app.schemas.base.CamelModel` (shared Pydantic base used by every schema from here on), `POST /auth/register` and `POST /auth/login` returning `{user: {id,name,email}, accessToken, refreshToken}`.

- [ ] **Step 1: Create `app/schemas/__init__.py`** (empty)

- [ ] **Step 2: Create `app/schemas/base.py`**

```python
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
```

- [ ] **Step 3: Create `app/schemas/auth.py`**

```python
from pydantic import EmailStr, Field

from app.schemas.base import CamelModel


class RegisterRequest(CamelModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(CamelModel):
    email: EmailStr
    password: str


class UserOut(CamelModel):
    id: str
    name: str
    email: EmailStr


class TokenPair(CamelModel):
    user: UserOut
    access_token: str
    refresh_token: str
```

- [ ] **Step 4: Create `app/routers/__init__.py`** (empty)

- [ ] **Step 5: Write the failing auth tests**

`tests/test_auth.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_tokens(client):
    response = await client.post(
        "/auth/register",
        json={"name": "Ana", "email": "ana@example.com", "password": "s3cret!"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["email"] == "ana@example.com"
    assert body["accessToken"]
    assert body["refreshToken"]


@pytest.mark.asyncio
async def test_register_duplicate_email_returns_409(client):
    payload = {"name": "Ana", "email": "dup@example.com", "password": "s3cret!"}
    await client.post("/auth/register", json=payload)

    response = await client.post("/auth/register", json=payload)

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_login_with_correct_credentials_returns_tokens(client):
    await client.post(
        "/auth/register",
        json={"name": "Beto", "email": "beto@example.com", "password": "correcthorse"},
    )

    response = await client.post(
        "/auth/login", json={"email": "beto@example.com", "password": "correcthorse"}
    )

    assert response.status_code == 200
    assert response.json()["accessToken"]


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(client):
    await client.post(
        "/auth/register",
        json={"name": "Beto", "email": "beto2@example.com", "password": "correcthorse"},
    )

    response = await client.post(
        "/auth/login", json={"email": "beto2@example.com", "password": "wrong"}
    )

    assert response.status_code == 401
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `client` fixture works, but `/auth/register` doesn't exist yet (404).

- [ ] **Step 7: Create `app/routers/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token, hash_password, hash_token, verify_password
from app.db import get_db
from app.models.user import RefreshToken, User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenPair, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


async def _issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(user.id)
    refresh_token, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, token_hash=hash_token(refresh_token), expires_at=expires_at))
    await db.commit()
    return access_token, refresh_token


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(name=payload.name, email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    await db.flush()

    access_token, refresh_token = await _issue_tokens(db, user)
    return TokenPair(user=UserOut.model_validate(user), access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenPair)
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenPair:
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    access_token, refresh_token = await _issue_tokens(db, user)
    return TokenPair(user=UserOut.model_validate(user), access_token=access_token, refresh_token=refresh_token)
```

- [ ] **Step 8: Register the router in `app/main.py`**

Add to `app/main.py`, after `app.add_middleware(SlowAPIMiddleware)`:

```python
from app.routers import auth

app.include_router(auth.router)
```

(Merge this import with any existing imports at the top of the file.)

- [ ] **Step 9: Run tests to verify they pass**

Run (PowerShell): `$env:DATABASE_URL="mysql+aiomysql://root:root@localhost:3306/maize_doctor_test"; pytest tests/test_auth.py -v`
Expected: PASS (4 tests).

- [ ] **Step 10: Commit**

```bash
git add app/schemas app/routers/__init__.py app/routers/auth.py app/main.py tests/test_auth.py
git commit -m "feat: add auth register and login endpoints"
```

---

### Task 5: Auth refresh, logout, and get_current_user dependency

**Files:**
- Create: `maize-doctor-api/app/core/deps.py`
- Modify: `maize-doctor-api/app/schemas/auth.py`
- Modify: `maize-doctor-api/app/routers/auth.py`
- Modify: `maize-doctor-api/tests/test_auth.py`

**Interfaces:**
- Consumes: `app.core.security.{decode_token,utcnow,hash_token}` (Task 3), `app.models.user.{User,RefreshToken}` (Task 2), `app.schemas.auth.TokenPair` pattern (Task 4).
- Produces: `app.core.deps.get_current_user` (FastAPI dependency returning the authenticated `User`, raises 401), used by every protected router from here on. `POST /auth/refresh` and `POST /auth/logout`.

- [ ] **Step 1: Add refresh/logout schemas to `app/schemas/auth.py`**

Append:
```python
class RefreshRequest(CamelModel):
    refresh_token: str


class LogoutRequest(CamelModel):
    refresh_token: str


class RefreshedTokens(CamelModel):
    access_token: str
    refresh_token: str
```

- [ ] **Step 2: Write the failing refresh/logout tests**

Append to `tests/test_auth.py`:
```python
@pytest.mark.asyncio
async def test_refresh_returns_new_token_pair(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Cora", "email": "cora@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]

    response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    assert response.status_code == 200
    body = response.json()
    assert body["accessToken"]
    assert body["refreshToken"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_rejects_reused_token(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Dana", "email": "dana@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]
    await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token(client):
    register_response = await client.post(
        "/auth/register",
        json={"name": "Eli", "email": "eli@example.com", "password": "correcthorse"},
    )
    refresh_token = register_response.json()["refreshToken"]

    logout_response = await client.post("/auth/logout", json={"refreshToken": refresh_token})
    assert logout_response.status_code == 204

    reuse_response = await client.post("/auth/refresh", json={"refreshToken": refresh_token})
    assert reuse_response.status_code == 401
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_auth.py -v -k refresh_or_logout or refresh or logout`
Expected: FAIL — `/auth/refresh` and `/auth/logout` don't exist yet (404).

- [ ] **Step 4: Add refresh/logout handlers to `app/routers/auth.py`**

Add imports and append to the file:
```python
from app.core.security import utcnow
from app.schemas.auth import LogoutRequest, RefreshedTokens, RefreshRequest


@router.post("/refresh", response_model=RefreshedTokens)
@limiter.limit("10/minute")
async def refresh(request: Request, payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> RefreshedTokens:
    token_hash = hash_token(payload.refresh_token)
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))

    if stored is None or stored.revoked_at is not None or stored.expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    stored.revoked_at = utcnow()
    user = await db.get(User, stored.user_id)

    access_token, new_refresh_token = await _issue_tokens(db, user)
    return RefreshedTokens(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest, db: AsyncSession = Depends(get_db)) -> None:
    token_hash = hash_token(payload.refresh_token)
    stored = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if stored is not None:
        stored.revoked_at = utcnow()
        await db.commit()
```

(Merge the `from app.core.security import ...` and `from app.schemas.auth import ...` lines with the existing imports at the top of `app/routers/auth.py` rather than duplicating them.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_auth.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 6: Create `app/core/deps.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db import get_db
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

    user = await db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user
```

There's no standalone test for this dependency here — it's exercised end-to-end by the `/corrections` auth tests in Task 6, which is the first consumer.

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `pytest -v`
Expected: PASS (all tests from Tasks 1-5 green).

- [ ] **Step 8: Commit**

```bash
git add app/core/deps.py app/schemas/auth.py app/routers/auth.py tests/test_auth.py
git commit -m "feat: add auth refresh, logout, and get_current_user dependency"
```

---

### Task 6: POST /corrections

**Files:**
- Create: `maize-doctor-api/app/schemas/correction.py`
- Create: `maize-doctor-api/app/routers/corrections.py`
- Modify: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_corrections.py`

**Interfaces:**
- Consumes: `app.core.deps.get_current_user` (Task 5), `app.core.rate_limit.{limiter,user_or_ip_key}` (Task 3), `app.models.correction.Correction` (Task 2), `app.schemas.base.CamelModel` (Task 4).
- Produces: `POST /corrections` accepting `{clientId, scanId, observedLabel, note, status, createdAt}`, returning `CorrectionOut` with 201 (new) or 200 (idempotent replay).

- [ ] **Step 1: Create `app/schemas/correction.py`**

```python
from datetime import datetime

from app.schemas.base import CamelModel


class CorrectionIn(CamelModel):
    client_id: str
    scan_id: str
    observed_label: str
    note: str | None = None
    status: str = "pending"
    created_at: datetime


class CorrectionOut(CamelModel):
    id: str
    client_id: str
    status: str
    created_at: datetime
```

- [ ] **Step 2: Write the failing corrections tests**

`tests/test_corrections.py`:
```python
from datetime import datetime, timezone

import pytest


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register", json={"name": "Farmer", "email": email, "password": "correcthorse"}
    )
    return response.json()["accessToken"]


@pytest.mark.asyncio
async def test_create_correction_requires_auth(client):
    response = await client.post(
        "/corrections",
        json={
            "clientId": "local-1",
            "scanId": "scan-1",
            "observedLabel": "common_rust",
            "note": None,
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_correction_returns_201(client):
    token = await _register_and_get_token(client, "farmer1@example.com")

    response = await client.post(
        "/corrections",
        json={
            "clientId": "local-1",
            "scanId": "scan-1",
            "observedLabel": "common_rust",
            "note": "leaf had visible pustules",
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["clientId"] == "local-1"


@pytest.mark.asyncio
async def test_replaying_same_client_id_is_idempotent(client):
    token = await _register_and_get_token(client, "farmer2@example.com")
    payload = {
        "clientId": "local-2",
        "scanId": "scan-2",
        "observedLabel": "gray_leaf_spot",
        "note": None,
        "status": "pending",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/corrections", json=payload, headers=headers)
    second = await client.post("/corrections", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_corrections.py -v`
Expected: FAIL — `/corrections` doesn't exist yet (404).

- [ ] **Step 4: Create `app/routers/corrections.py`**

```python
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.security import utcnow
from app.db import get_db
from app.models.correction import Correction
from app.models.user import User
from app.schemas.correction import CorrectionIn, CorrectionOut

router = APIRouter(prefix="/corrections", tags=["corrections"])


@router.post("", response_model=CorrectionOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def create_correction(
    request: Request,
    payload: CorrectionIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrectionOut:
    existing = await db.scalar(
        select(Correction).where(Correction.user_id == user.id, Correction.client_id == payload.client_id)
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return CorrectionOut.model_validate(existing)

    correction = Correction(
        user_id=user.id,
        client_id=payload.client_id,
        scan_id=payload.scan_id,
        observed_label=payload.observed_label,
        note=payload.note,
        status=payload.status,
        created_at=payload.created_at.replace(tzinfo=None),
        received_at=utcnow(),
    )
    db.add(correction)
    await db.commit()
    await db.refresh(correction)
    return CorrectionOut.model_validate(correction)
```

- [ ] **Step 5: Register the router in `app/main.py`**

```python
from app.routers import auth, corrections

app.include_router(auth.router)
app.include_router(corrections.router)
```

(Merge with the existing `from app.routers import auth` line rather than duplicating it.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_corrections.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/schemas/correction.py app/routers/corrections.py app/main.py tests/test_corrections.py
git commit -m "feat: add POST /corrections with idempotent sync"
```

---

### Task 7: Image storage (PIL validation + disk save)

**Files:**
- Create: `maize-doctor-api/app/storage.py`
- Test: `maize-doctor-api/tests/test_storage.py`

**Interfaces:**
- Consumes: `app.config.settings.{upload_dir,max_upload_size_mb}` (Task 1).
- Produces: `app.storage.save_upload_image(upload: fastapi.UploadFile, subdir: str) -> str` (returns the saved file's path), `app.storage.InvalidImageError`, `app.storage.FileTooLargeError` — consumed by Task 8's `/dataset-contributions` endpoint.

- [ ] **Step 1: Write the failing storage tests**

`tests/test_storage.py`:
```python
import io

import pytest
from fastapi import UploadFile
from PIL import Image

from app.storage import FileTooLargeError, InvalidImageError, save_upload_image


def _make_png_upload(filename: str = "leaf.png") -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(filename=filename, file=buffer)


@pytest.mark.asyncio
async def test_save_valid_image_returns_path_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = _make_png_upload()

    path = await save_upload_image(upload, subdir="dataset-contributions")

    assert path.endswith(".png")
    assert (tmp_path / "dataset-contributions").exists()


@pytest.mark.asyncio
async def test_corrupt_image_raises_invalid_image_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = UploadFile(filename="broken.png", file=io.BytesIO(b"not a real image"))

    with pytest.raises(InvalidImageError):
        await save_upload_image(upload, subdir="dataset-contributions")


@pytest.mark.asyncio
async def test_oversized_image_raises_file_too_large_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    monkeypatch.setattr("app.storage.settings.max_upload_size_mb", 0)
    upload = _make_png_upload()

    with pytest.raises(FileTooLargeError):
        await save_upload_image(upload, subdir="dataset-contributions")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.storage'`.

- [ ] **Step 3: Create `app/storage.py`**

```python
import io
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import settings


class InvalidImageError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


async def save_upload_image(upload: UploadFile, subdir: str) -> str:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    contents = await upload.read()
    if len(contents) > max_bytes:
        raise FileTooLargeError(f"File exceeds {settings.max_upload_size_mb}MB limit")

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("Uploaded file is not a valid image") from exc

    extension = Path(upload.filename or "").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{extension}"
    target_dir = Path(settings.upload_dir) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_bytes(contents)

    return str(target_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/storage.py tests/test_storage.py
git commit -m "feat: add image upload storage with PIL validation"
```

---

### Task 8: POST /dataset-contributions

**Files:**
- Create: `maize-doctor-api/app/schemas/contribution.py`
- Create: `maize-doctor-api/app/routers/contributions.py`
- Modify: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_contributions.py`

**Interfaces:**
- Consumes: `app.core.deps.get_current_user` (Task 5), `app.core.rate_limit.{limiter,user_or_ip_key}` (Task 3), `app.storage.{save_upload_image,InvalidImageError,FileTooLargeError}` (Task 7), `app.models.contribution.DatasetContribution` (Task 2).
- Produces: `POST /dataset-contributions` (multipart), returning `ContributionOut` with 201 (new) or 200 (idempotent replay), 422 on invalid image, 413 on oversized.

- [ ] **Step 1: Create `app/schemas/contribution.py`**

```python
from datetime import datetime

from app.schemas.base import CamelModel


class ContributionOut(CamelModel):
    id: str
    client_id: str
    label: str
    status: str
    created_at: datetime
```

- [ ] **Step 2: Write the failing contributions tests**

`tests/test_contributions.py`:
```python
import io
from datetime import datetime, timezone

import pytest
from PIL import Image


async def _register_and_get_token(client, email: str) -> str:
    response = await client.post(
        "/auth/register", json={"name": "Farmer", "email": email, "password": "correcthorse"}
    )
    return response.json()["accessToken"]


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_create_contribution_requires_auth(client):
    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-1",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_contribution_returns_201(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower1@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-1",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201
    assert response.json()["label"] == "common_rust"


@pytest.mark.asyncio
async def test_replaying_same_client_id_is_idempotent(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower2@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    data = {
        "clientId": "local-2",
        "label": "gray_leaf_spot",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    files = {"image": ("leaf.png", _png_bytes(), "image/png")}

    first = await client.post("/dataset-contributions", data=data, files=files, headers=headers)
    second = await client.post("/dataset-contributions", data=data, files=files, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


@pytest.mark.asyncio
async def test_corrupt_image_returns_422(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower3@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-3",
            "label": "common_rust",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("broken.png", b"not a real image", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_contributions.py -v`
Expected: FAIL — `/dataset-contributions` doesn't exist yet (404).

- [ ] **Step 4: Create `app/routers/contributions.py`**

```python
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.security import utcnow
from app.db import get_db
from app.models.contribution import DatasetContribution
from app.models.user import User
from app.schemas.contribution import ContributionOut
from app.storage import FileTooLargeError, InvalidImageError, save_upload_image

router = APIRouter(prefix="/dataset-contributions", tags=["contributions"])


@router.post("", response_model=ContributionOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def create_contribution(
    request: Request,
    response: Response,
    client_id: str = Form(..., alias="clientId"),
    label: str = Form(...),
    note: str | None = Form(None),
    created_at: datetime = Form(..., alias="createdAt"),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContributionOut:
    existing = await db.scalar(
        select(DatasetContribution).where(
            DatasetContribution.user_id == user.id, DatasetContribution.client_id == client_id
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return ContributionOut.model_validate(existing)

    try:
        image_path = await save_upload_image(image, subdir="dataset-contributions")
    except InvalidImageError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    contribution = DatasetContribution(
        user_id=user.id,
        client_id=client_id,
        image_path=image_path,
        label=label,
        note=note,
        created_at=created_at.replace(tzinfo=None),
        received_at=utcnow(),
    )
    db.add(contribution)
    await db.commit()
    await db.refresh(contribution)
    return ContributionOut.model_validate(contribution)
```

- [ ] **Step 5: Register the router in `app/main.py`**

```python
from app.routers import auth, contributions, corrections

app.include_router(auth.router)
app.include_router(corrections.router)
app.include_router(contributions.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_contributions.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full test suite to confirm nothing broke**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/schemas/contribution.py app/routers/contributions.py app/main.py tests/test_contributions.py
git commit -m "feat: add POST /dataset-contributions with image upload"
```

---

### Task 9: GET /app-version

**Files:**
- Create: `maize-doctor-api/app/schemas/app_version.py`
- Create: `maize-doctor-api/app/routers/app_version.py`
- Modify: `maize-doctor-api/app/main.py`
- Test: `maize-doctor-api/tests/test_app_version.py`

**Interfaces:**
- Consumes: `app.core.rate_limit.limiter` (Task 3), `app.models.app_release.AppRelease` (Task 2).
- Produces: `GET /app-version?platform=&currentVersionCode=` returning `AppVersionOut`.

- [ ] **Step 1: Create `app/schemas/app_version.py`**

```python
from app.schemas.base import CamelModel


class AppVersionOut(CamelModel):
    latest_version_code: int
    latest_version_name: str
    min_supported_version_code: int
    force_update: bool
    download_url: str
    release_notes: str | None
```

- [ ] **Step 2: Write the failing app-version tests**

`tests/test_app_version.py`:
```python
import pytest

from app.models.app_release import AppRelease


@pytest.mark.asyncio
async def test_returns_404_when_no_release_exists(client):
    response = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 1})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_returns_latest_release_and_force_update_false(client, db_session):
    db_session.add(
        AppRelease(
            platform="android",
            version_code=10,
            version_name="1.2.0",
            min_supported_version_code=8,
            download_url="https://example.com/app.apk",
            release_notes="Bug fixes",
        )
    )
    await db_session.commit()

    response = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 9})

    assert response.status_code == 200
    body = response.json()
    assert body["latestVersionCode"] == 10
    assert body["forceUpdate"] is False


@pytest.mark.asyncio
async def test_force_update_true_when_below_minimum(client, db_session):
    db_session.add(
        AppRelease(
            platform="android",
            version_code=10,
            version_name="1.2.0",
            min_supported_version_code=8,
            download_url="https://example.com/app.apk",
            release_notes=None,
        )
    )
    await db_session.commit()

    response = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 5})

    assert response.status_code == 200
    assert response.json()["forceUpdate"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_app_version.py -v`
Expected: FAIL — `/app-version` doesn't exist yet (404 for all, but test 1 happens to expect 404 for the wrong reason; tests 2 and 3 fail).

- [ ] **Step 4: Create `app/routers/app_version.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db import get_db
from app.models.app_release import AppRelease
from app.schemas.app_version import AppVersionOut

router = APIRouter(tags=["app-version"])


@router.get("/app-version", response_model=AppVersionOut)
@limiter.limit("60/minute")
async def get_app_version(
    request: Request,
    platform: str = Query(...),
    current_version_code: int = Query(..., alias="currentVersionCode"),
    db: AsyncSession = Depends(get_db),
) -> AppVersionOut:
    release = await db.scalar(
        select(AppRelease)
        .where(AppRelease.platform == platform, AppRelease.is_active.is_(True))
        .order_by(AppRelease.version_code.desc())
        .limit(1)
    )
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No release found for platform")

    return AppVersionOut(
        latest_version_code=release.version_code,
        latest_version_name=release.version_name,
        min_supported_version_code=release.min_supported_version_code,
        force_update=current_version_code < release.min_supported_version_code,
        download_url=release.download_url,
        release_notes=release.release_notes,
    )
```

- [ ] **Step 5: Register the router in `app/main.py`**

```python
from app.routers import app_version, auth, contributions, corrections

app.include_router(auth.router)
app.include_router(corrections.router)
app.include_router(contributions.router)
app.include_router(app_version.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_app_version.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add app/schemas/app_version.py app/routers/app_version.py app/main.py tests/test_app_version.py
git commit -m "feat: add GET /app-version endpoint"
```

---

### Task 10: Rate-limit enforcement test, full-stack Docker smoke test, README

**Files:**
- Create: `maize-doctor-api/tests/test_rate_limit.py`
- Modify: `maize-doctor-api/README.md`

**Interfaces:**
- Consumes: everything built in Tasks 1-9. No new interfaces produced — this task verifies the assembled system end to end.

- [ ] **Step 1: Write the rate-limit enforcement test**

`tests/test_rate_limit.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_five_requests_per_minute(client):
    payload = {"email": "nope@example.com", "password": "wrong"}

    responses = [await client.post("/auth/login", json=payload) for _ in range(6)]

    assert responses[-1].status_code == 429
    assert any(r.status_code == 401 for r in responses[:5])
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `pytest tests/test_rate_limit.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: PASS — every test from Tasks 1-10 green.

- [ ] **Step 4: Build and boot the full stack via Docker Compose**

Run:
```bash
cd maize-doctor-api
docker compose up -d --build
```
Expected: both `mysql` and `api` services report `Up` (mysql `healthy`) via `docker compose ps`.

- [ ] **Step 5: Apply migrations against the containerized MySQL and smoke-test the running API**

Run:
```bash
docker compose exec api alembic upgrade head
curl -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d "{\"name\":\"Smoke Test\",\"email\":\"smoke@example.com\",\"password\":\"correcthorse\"}"
curl http://localhost:8000/health
```
Expected: register returns 201 with `accessToken`/`refreshToken`; `/health` returns `{"status":"ok"}`.

- [ ] **Step 6: Write `README.md`**

```markdown
# maize-doctor-api

Backend for `maize-doctor-app` (offline-first). Serves exactly two things:

1. App-version check (`GET /app-version`) — tells the app whether an update is available/required.
2. Optional sync when online: `POST /corrections` and `POST /dataset-contributions`. No scan telemetry is collected.

See `docs/superpowers/specs/2026-08-16-maize-doctor-api-design.md` for the full design.

## Local development

```bash
cp .env.example .env
docker compose up -d mysql
python -m venv .venv && .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Running tests

Tests run against a real MySQL instance (started via Docker Compose), not a mock:

```bash
docker compose up -d mysql
$env:DATABASE_URL="mysql+aiomysql://root:root@localhost:3306/maize_doctor_test"
pytest -v
```

## Publishing a new app release

There's no admin endpoint for this in v1 — insert a row directly:

```sql
INSERT INTO app_releases (id, platform, version_code, version_name, min_supported_version_code, download_url, release_notes, published_at, is_active)
VALUES (UUID(), 'android', 11, '1.3.0', 8, 'https://example.com/app-1.3.0.apk', 'Bug fixes', NOW(), TRUE);
```

## Full stack via Docker Compose

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_rate_limit.py README.md
git commit -m "test: verify rate limiting end to end; add README"
```

---

## Follow-up (not part of this plan)

`maize-doctor-app/src/api/FastApiSyncClient.ts` needs a corresponding update to send `dataset-contributions` as `multipart/form-data` with the actual image file instead of a JSON `imageUri` string — flagged in the spec, out of scope for this repo's plan.
