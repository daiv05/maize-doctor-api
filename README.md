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

## Pointing `maize-doctor-app` at this API

The app reads the base URL from `EXPO_PUBLIC_API_URL` (see that repo's `.env`). This API has no CORS layer by design (`docs/superpowers/specs/2026-08-16-maize-doctor-api-design.md`) because the app calls it directly via `fetch`, not from a browser — so any reachable host:port works, there's nothing to allow-list.

- **Android emulator** talking to a server on the same host machine: `http://10.0.2.2:8000` (`localhost` from inside the emulator refers to the emulator itself, not the host).
- **Physical device** on the same network as the dev machine: `http://<dev-machine-LAN-IP>:8000` — find the IP with `ipconfig` (Windows) and make sure `docker compose up` is exposing port 8000 on all interfaces (it already does, per `docker-compose.yml`'s `ports: ["8000:8000"]`).
- **iOS simulator**: `http://localhost:8000` works as-is (the simulator shares the host's network namespace).
- **Staging/production**: no such deployment exists yet as of this API's v1 scope — when one does, document its URL here instead of leaving `EXPO_PUBLIC_API_URL` to be guessed per-developer.

Leaving `EXPO_PUBLIC_API_URL` unset is a supported configuration, not a broken one: the app falls back to its `MockSyncClient` and skips remote sessions entirely, so it stays fully usable offline.

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

## Deployment notes

Rate limiting is in-memory and keys on the client's socket address, which has two consequences:

- **Behind a reverse proxy**, every request appears to come from the proxy, so one client's bursts
  would exhaust the limit for everyone. Run uvicorn with
  `--proxy-headers --forwarded-allow-ips=<proxy-ip>` so `X-Forwarded-For` is trusted and the limits
  key per real client.
- **Keep it at one worker.** The Dockerfile runs a single uvicorn worker on purpose: each worker
  holds its own counters, so N workers silently multiply every documented limit by N.

## Full stack via Docker Compose

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```
