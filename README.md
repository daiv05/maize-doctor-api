# maize-doctor-api

Backend de `maize-doctor-app` (offline-first). La app funciona completa sin esta API; lo que
el backend aporta es cuenta de usuario, sincronización opcional y aviso de actualizaciones.
No se recoge telemetría de escaneos.

## Endpoints

| Método | Ruta | Límite | Autenticación |
|---|---|---:|---|
| `GET` | `/health` | - | - |
| `POST` | `/auth/register` | 5/min | - |
| `POST` | `/auth/login` | 5/min | - |
| `POST` | `/auth/refresh` | 10/min | refresh token |
| `POST` | `/auth/logout` | - | refresh token |
| `POST` | `/corrections` | 30/min | access token opcional |
| `POST` | `/dataset-contributions` | 30/min | access token opcional |
| `GET` | `/app-version` | 60/min | - |
| `POST` | `/app-releases` | 10/min | `RELEASE_ADMIN_TOKEN` |

`/corrections` y `/dataset-contributions` limitan por usuario cuando llega un access token
válido y por IP en caso contrario (`app/core/rate_limit.py`), de modo que varios usuarios tras
la misma NAT no se consumen la cuota entre sí.

## Desarrollo local

```bash
cp .env.example .env
docker compose up -d mysql
python -m venv .venv && .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

## Apuntar `maize-doctor-app` a esta API

La app lee la URL base de `EXPO_PUBLIC_API_URL` (ver el `.env` de ese repositorio). Esta API no
tiene capa CORS por la simplicidad del prototipo. Cualquier uso en producción debe tener en cuenta esto.

- **Emulador de Android** contra un servidor en la misma máquina: `http://10.0.2.2:8000`
  (`localhost` dentro del emulador se refiere al emulador, no al anfitrión).
- **Simulador de iOS**: `http://localhost:8000` funciona tal cual.
- **Dispositivo físico** en la misma red que la máquina de desarrollo:
  `http://<IP-LAN-de-la-máquina>:8000`, obtenida con `ipconfig`. Requiere un paso extra:
  `docker-compose.yml` publica el puerto en `127.0.0.1:8000:8000`, es decir solo en loopback,
  así que un teléfono de la LAN **no** alcanza el contenedor. Para probar en dispositivo físico,
  corre uvicorn fuera de Docker escuchando en todas las interfaces:

  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```

  Exponer el contenedor a la LAN cambiando esa publicación anula el aislamiento que introdujo
  `ae3d180`; hazlo solo de forma temporal y en una red de confianza.
- **Producción**: `https://api.maize-doctor.deras.dev`. La app fija este valor en su
  `.env.production`, que Expo carga para los builds de release (ver
  `maize-doctor-app/docs/build-produccion.md`); queda incrustado en el APK al compilar, de modo
  que cambiarlo exige un rebuild.

Dejar `EXPO_PUBLIC_API_URL` sin definir es una configuración soportada, no un fallo: la app cae
a su `MockSyncClient`, omite las sesiones remotas y sigue siendo plenamente utilizable offline.

## Pruebas

Las pruebas corren contra una instancia real de MySQL levantada con Docker Compose, no contra un
mock. El esquema de prueba se construye con Alembic:

```bash
docker compose up -d mysql
$env:DATABASE_URL="mysql+aiomysql://root:root@localhost:3306/maize_doctor_test"
pytest -v
```

## Publicar una versión de la app

Normalmente no hace falta: el workflow `Release APK` de `maize-doctor-app` compila el APK en cada merge a `main`, lo publica como asset de una release de GitHub y lo registra aquí llamando a
`POST /app-releases`.

### `POST /app-releases`

Protegido por un secreto compartido en `RELEASE_ADMIN_TOKEN`, enviado como
`Authorization: Bearer <token>`. **El endpoint queda cerrado mientras ese ajuste esté vacío**: un token sin configurar rechaza a todos en lugar de dejar pasar a cualquiera, de modo que un
despliegue que nunca lo configure no puede recibir publicaciones.

```bash
curl -X POST https://api.maize-doctor.deras.dev/app-releases \
  -H "Authorization: Bearer $RELEASE_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "platform": "android",
        "versionCode": 12,
        "versionName": "1.4.0",
        "minSupportedVersionCode": 8,
        "downloadUrl": "https://github.com/<owner>/<repo>/releases/download/v1.4.0+12/app.apk",
        "releaseNotes": null
      }'
```

Publicar **desactiva las releases anteriores de esa plataforma**, de forma que solo queda una
fila activa. `GET /app-version` elige el `version_code` activo más alto, así que dejar filas
viejas activas permitiría que un build antiguo ganara después de un rollback.

Rechaza: un `version_code` duplicado para la plataforma (409), un `download_url` que no sea
`https` (422) y cualquier `platform` distinta de `android`/`ios` (422).

### A mano

Para insertar una fila directamente (un rollback, o una release construida fuera de CI):

```sql
INSERT INTO app_releases (id, platform, version_code, version_name, min_supported_version_code, download_url, release_notes, published_at, is_active)
VALUES (UUID(), 'android', 11, '1.3.0', 8, 'https://example.com/app-1.3.0.apk', 'Bug fixes', NOW(), TRUE);
```

Sobre los campos, tal como los consume la app (`maize-doctor-app/src/api/AppUpdateService.ts`):

- `version_code` debe coincidir con el `expo.android.versionCode` del APK compilado. La app
  ignora cualquier release cuyo `version_code` no sea mayor que el instalado, así que una errata
  aquí hace que la actualización nunca aparezca, en silencio.
- `min_supported_version_code` es lo que vuelve **obligatoria** una actualización: la app muestra
  un diálogo sin salida a quien tenga un `version_code` instalado por debajo de ese valor.
  Déjalo en la versión más antigua que aún quieras soportar; subirlo deja a esos usuarios fuera
  de la app hasta que instalen el APK nuevo.
- `download_url` debe apuntar a un APK real y públicamente alcanzable: esta API no aloja el
  binario. La app abre la URL con `Linking.openURL`.
- `platform` se compara contra el `Platform.OS` de React Native, así que usa `android`/`ios`.

## Notas de despliegue

El rate limiting vive en memoria y se indexa por la dirección del socket del cliente, lo que
tiene dos consecuencias:

- **Detrás de un proxy inverso**, toda petición parece venir del proxy, así que las ráfagas de un
  cliente agotarían el límite de todos. `docker-compose.yml` ya arranca uvicorn con
  `--proxy-headers --forwarded-allow-ips=172.18.0.1`, la puerta de enlace de la red declarada en
  ese mismo archivo: solo se confía en el `X-Forwarded-For` de ese origen. Si el proxy corre en
  otra dirección, hay que ajustar ambos valores a la vez.
- **Un solo worker.** El Dockerfile arranca un único worker de uvicorn a propósito: cada worker
  mantiene sus propios contadores, de modo que N workers multiplicarían en silencio por N todos
  los límites documentados.

Tanto MySQL como la API se publican en `127.0.0.1` (`ae3d180`). El proxy inverso del anfitrión es
el único que debería alcanzarlas.

## Stack completo con Docker Compose

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```
