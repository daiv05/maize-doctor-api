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
