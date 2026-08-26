import pytest

from app.config import settings
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


ADMIN_TOKEN = "test-release-token"
RELEASE_BODY = {
    "platform": "android",
    "versionCode": 12,
    "versionName": "1.4.0",
    "minSupportedVersionCode": 8,
    "downloadUrl": "https://github.com/owner/repo/releases/download/v1.4.0/app.apk",
    "releaseNotes": "Nuevo modelo",
}


@pytest.fixture
def admin_token(monkeypatch):
    monkeypatch.setattr(settings, "release_admin_token", ADMIN_TOKEN)
    return ADMIN_TOKEN


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_publish_release_requires_a_token(client, admin_token):
    response = await client.post("/app-releases", json=RELEASE_BODY)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_publish_release_rejects_a_wrong_token(client, admin_token):
    response = await client.post("/app-releases", json=RELEASE_BODY, headers=auth("nope"))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_publish_release_is_closed_when_no_token_is_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "release_admin_token", "")

    response = await client.post("/app-releases", json=RELEASE_BODY, headers=auth("anything"))

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_publish_release_stores_it_and_app_version_serves_it(client, admin_token):
    created = await client.post("/app-releases", json=RELEASE_BODY, headers=auth(ADMIN_TOKEN))
    assert created.status_code == 201
    assert created.json()["versionCode"] == 12

    served = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 9})

    assert served.status_code == 200
    body = served.json()
    assert body["latestVersionCode"] == 12
    assert body["downloadUrl"] == RELEASE_BODY["downloadUrl"]
    assert body["forceUpdate"] is False

    forced = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 7})

    assert forced.json()["forceUpdate"] is True


@pytest.mark.asyncio
async def test_publishing_deactivates_the_previous_release(client, admin_token, db_session):
    await client.post("/app-releases", json=RELEASE_BODY, headers=auth(ADMIN_TOKEN))
    rollback = {**RELEASE_BODY, "versionCode": 11, "versionName": "1.3.0"}
    await client.post("/app-releases", json=rollback, headers=auth(ADMIN_TOKEN))

    served = await client.get("/app-version", params={"platform": "android", "currentVersionCode": 1})

    assert served.json()["latestVersionCode"] == 11


@pytest.mark.asyncio
async def test_publish_release_rejects_a_duplicate_version_code(client, admin_token):
    await client.post("/app-releases", json=RELEASE_BODY, headers=auth(ADMIN_TOKEN))

    duplicate = await client.post("/app-releases", json=RELEASE_BODY, headers=auth(ADMIN_TOKEN))

    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_publish_release_rejects_a_non_https_url(client, admin_token):
    body = {**RELEASE_BODY, "downloadUrl": "http://insecure.example.com/app.apk"}

    response = await client.post("/app-releases", json=body, headers=auth(ADMIN_TOKEN))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_publish_release_rejects_an_unknown_platform(client, admin_token):
    body = {**RELEASE_BODY, "platform": "windows"}

    response = await client.post("/app-releases", json=body, headers=auth(ADMIN_TOKEN))

    assert response.status_code == 422
