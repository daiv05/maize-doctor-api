# maize-doctor-api — Design Spec

## Contexto

`maize-doctor-app` (React Native + Expo) hace inferencia CNN completamente offline (TFLite embebido en el APK). Esta API es el único componente en línea del sistema y cubre exactamente dos funciones:

1. **Chequeo de actualizaciones de la app** (versión de APK, no del modelo — el modelo viaja embebido y se actualiza junto con una nueva versión de la app).
2. **Sincronización opcional cuando hay conexión**, limitada a `corrections` (correcciones del usuario a un diagnóstico) y `dataset-contributions` (imágenes donadas explícitamente para reentrenar el modelo). **No incluye `scans`** (sin telemetría de cada inferencia local).

Fuente de verdad del lado app: `src/api/SyncClient.ts`, `src/api/FastApiSyncClient.ts`, `src/api/syncQueue.ts`, `src/data/models/Correction.ts`, `src/data/models/DatasetContribution.ts`, `src/auth/AuthService.ts` en `maize-doctor-app`. `model-ml.md` fija el stack de sync como FastAPI + MySQL.

## Decisiones de alcance (confirmadas con el usuario)

- Solo `/corrections` y `/dataset-contributions` sincronizan; `/scans` queda fuera (decisión explícita: "NADA de telemetría").
- Auth real de usuario (cuentas en servidor, no solo un `deviceId`), porque correcciones/contribuciones deben poder atribuirse a una persona.
- Moderación de contribuciones: la API solo almacena con estado `pending`; la revisión para decidir qué entra a `clean/` del pipeline de ML es un proceso humano fuera de esta API (sin endpoints de aprobación/rechazo en v1).
- El chequeo de actualizaciones es solo de la app (APK/AAB); no distribuye el modelo por separado.
- Las imágenes se guardan en disco local del servidor (no object storage externo) — alcance académico, sin necesidad de escalar a múltiples instancias todavía.

## Stack

FastAPI, SQLAlchemy 2.0 (async) + Alembic, MySQL, JWT (`python-jose` + `passlib[bcrypt]`), `slowapi` para rate limiting, Docker Compose para desarrollo/tests/despliegue.

## Estructura del proyecto

```
maize-doctor-api/
  app/
    main.py
    config.py          # pydantic-settings: DB_URL, JWT_SECRET, UPLOAD_DIR, MAX_UPLOAD_SIZE_MB, ...
    db.py               # engine/session async
    models/             # SQLAlchemy ORM: User, RefreshToken, Correction, DatasetContribution, AppRelease
    schemas/             # Pydantic request/response DTOs
    routers/            # auth.py, corrections.py, contributions.py, app_version.py
    core/                # security.py (hash/JWT), deps.py (get_current_user), rate_limit.py (slowapi Limiter)
    storage.py           # guardado de multipart a disco + validación PIL
  alembic/
  tests/
  docker-compose.yml    # servicios api + mysql, volumen de uploads
  Dockerfile
  .env.example
```

## Modelo de datos

- **users**: `id` (uuid pk), `name`, `email` (unique), `password_hash`, `created_at`
- **refresh_tokens**: `id`, `user_id` fk, `token_hash`, `expires_at`, `revoked_at` nullable, `created_at`
- **corrections**: `id` (pk servidor), `user_id` fk, `client_id` (id local WatermelonDB del dispositivo), `scan_id` (string opaco — no hay tabla de scans en servidor porque no se sincronizan), `observed_label`, `note` nullable, `status` (`pending`|`reviewed`), `created_at` (hora del cliente), `received_at` (hora del servidor). **Unique (`user_id`, `client_id`)** para reintentos idempotentes.
- **dataset_contributions**: `id`, `user_id` fk, `client_id`, `image_path`, `label`, `note` nullable, `status` (`pending`|`approved`|`rejected`, default `pending`), `created_at`, `received_at`. Mismo unique (`user_id`, `client_id`).
- **app_releases**: `id`, `platform`, `version_code`, `version_name`, `min_supported_version_code`, `download_url`, `release_notes`, `published_at`, `is_active`

## Endpoints

### Auth
- `POST /auth/register` `{name, email, password}` → 201 `{user, accessToken, refreshToken}`. 409 si el email ya existe.
- `POST /auth/login` `{email, password}` → 200 `{user, accessToken, refreshToken}`. 401 si credenciales inválidas.
- `POST /auth/refresh` `{refreshToken}` → 200 `{accessToken, refreshToken}` (rota el refresh token).
- `POST /auth/logout` `{refreshToken}` → 204 (revoca el token).

### Corrections (Bearer auth)
- `POST /corrections` `{clientId, scanId, observedLabel, note, status, createdAt}` → 201, o 200 si `(user, clientId)` ya existe (replay idempotente, no error).

### Dataset contributions (Bearer auth)
- `POST /dataset-contributions` — `multipart/form-data`: campo `image` (archivo) + `clientId`, `label`, `note`, `createdAt` → 201 (mismo idempotency por `client_id`). La imagen se valida abriéndola con PIL antes de aceptar (422 si está corrupta o no es una imagen), tamaño máximo configurable (413 si se excede).

### App version
- `GET /app-version?platform=android&currentVersionCode=12` → 200 `{latestVersionCode, latestVersionName, minSupportedVersionCode, forceUpdate, downloadUrl, releaseNotes}`. `forceUpdate` se calcula en servidor: `currentVersionCode < minSupportedVersionCode`. No hay endpoint de publicación en v1 — una nueva fila de release se inserta manualmente (script/SQL directo) al cortar una versión nueva del APK.

## Manejo de errores

Formato por defecto de FastAPI (`{"detail": ...}`), sin envelope custom. 401 tokens inválidos/expirados/ausentes, 409 email duplicado, 422 validación o imagen corrupta, 413 archivo demasiado grande, 429 rate limit excedido (con header `Retry-After`).

## Rate limiting y anti-abuso

`slowapi` con backend en memoria (single-instance; migrable a Redis si se despliega con múltiples workers, sin cambiar la API).

| Endpoint | Límite |
|---|---|
| `POST /auth/login`, `POST /auth/register` | 5 req/min por IP |
| `POST /auth/refresh` | 10 req/min por IP |
| `POST /corrections`, `POST /dataset-contributions` | 30 req/min por usuario autenticado |
| `GET /app-version` | 60 req/min por IP |

No hay bloqueo de cuenta tras N intentos fallidos de login en v1 (requeriría tracking de intentos por usuario y flujo de desbloqueo) — el throttling por IP cubre la amenaza principal para el alcance de este proyecto. Se suma a las protecciones ya existentes: validación PIL de imágenes, límite de tamaño de archivo, y JWT en todos los endpoints de escritura.

## Testing

`pytest` + `httpx.AsyncClient`, ejecutado vía `docker compose` (MySQL real, no mock de base de datos, siguiendo la convención del proyecto de preferir Docker para tests). Cobertura mínima: registro/login/refresh/email duplicado, replay idempotente en corrections/contributions, rechazo de imagen corrupta, cálculo de `forceUpdate`, y verificación de rate limiting (429 tras exceder el umbral).

## Despliegue

`docker-compose.yml` con servicios `api` y `mysql`, volumen nombrado para `/data/uploads` y otro para datos de MySQL. Configuración vía `.env` (`JWT_SECRET`, `DB_URL`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB`). Sin CORS (la app RN llama directo vía `fetch`, no desde navegador).

## Fuera de alcance (v1, explícito)

- Sincronización de `scans` (telemetría de inferencias).
- Endpoints de aprobación/rechazo de contribuciones (moderación es proceso humano externo).
- Distribución del modelo `.tflite` por separado de la app.
- Object storage externo para imágenes.
- Bloqueo de cuenta tras intentos fallidos de login.
- Panel de administración para publicar releases.

## Cambio requerido (fuera de este repo, no incluido aquí)

`maize-doctor-app/src/api/FastApiSyncClient.ts` hoy envía `imageUri` (ruta local del dispositivo) como string dentro de JSON en `syncContribution`. Contra el endpoint real `POST /dataset-contributions` (multipart) esto no funciona — el cliente necesita leer el archivo local y adjuntarlo como `multipart/form-data`. Requiere su propio cambio en el repo de la app, fuera del alcance de este spec.
