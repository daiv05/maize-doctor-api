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
