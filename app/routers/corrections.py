from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
    user_id = user.id
    existing = await db.scalar(
        select(Correction).where(Correction.user_id == user_id, Correction.client_id == payload.client_id)
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return CorrectionOut.model_validate(existing)

    correction = Correction(
        user_id=user_id,
        client_id=payload.client_id,
        scan_id=payload.scan_id,
        observed_label=payload.observed_label,
        note=payload.note,
        status=payload.status,
        created_at=payload.created_at.replace(tzinfo=None),
        received_at=utcnow(),
    )
    db.add(correction)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(Correction).where(Correction.user_id == user_id, Correction.client_id == payload.client_id)
        )
        response.status_code = status.HTTP_200_OK
        return CorrectionOut.model_validate(existing)

    await db.refresh(correction)
    return CorrectionOut.model_validate(correction)
