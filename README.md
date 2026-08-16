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
