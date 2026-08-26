from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_release_admin
from app.core.rate_limit import limiter
from app.db import get_db
from app.models.app_release import AppRelease
from app.schemas.app_version import AppReleaseIn, AppReleaseOut, AppVersionOut

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


@router.post("/app-releases", response_model=AppReleaseOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def publish_app_release(
    request: Request,
    payload: AppReleaseIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_release_admin),
) -> AppReleaseOut:
    """
    Registers a freshly published build so installed apps can discover it.

    Deactivates the platform's previous releases, keeping exactly one active row
    per platform: `GET /app-version` picks the highest active version_code, so
    leaving stale rows active would let an older build win after a rollback.
    """
    existing = await db.scalar(
        select(AppRelease).where(
            AppRelease.platform == payload.platform,
            AppRelease.version_code == payload.version_code,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Release {payload.version_code} already exists for {payload.platform}",
        )

    await db.execute(
        update(AppRelease)
        .where(AppRelease.platform == payload.platform, AppRelease.is_active.is_(True))
        .values(is_active=False)
    )

    release = AppRelease(
        platform=payload.platform,
        version_code=payload.version_code,
        version_name=payload.version_name,
        min_supported_version_code=payload.min_supported_version_code,
        download_url=payload.download_url,
        release_notes=payload.release_notes,
    )
    db.add(release)
    await db.commit()
    await db.refresh(release)

    return AppReleaseOut.model_validate(release)
