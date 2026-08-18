from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DIAGNOSIS_LABELS
from app.core.deps import get_current_user
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.security import to_naive_utc, utcnow
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
    client_id: str = Form(..., alias="clientId", max_length=36),
    label: str = Form(..., max_length=64),
    note: str | None = Form(default=None, max_length=1000),
    created_at: datetime = Form(..., alias="createdAt"),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContributionOut:
    if label not in DIAGNOSIS_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label debe ser uno de: {DIAGNOSIS_LABELS}",
        )

    user_id = user.id
    existing = await db.scalar(
        select(DatasetContribution).where(
            DatasetContribution.user_id == user_id, DatasetContribution.client_id == client_id
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
        user_id=user_id,
        client_id=client_id,
        image_path=image_path,
        label=label,
        note=note,
        created_at=to_naive_utc(created_at),
        received_at=utcnow(),
    )
    db.add(contribution)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        existing = await db.scalar(
            select(DatasetContribution).where(
                DatasetContribution.user_id == user_id, DatasetContribution.client_id == client_id
            )
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save contribution"
            ) from exc
        response.status_code = status.HTTP_200_OK
        return ContributionOut.model_validate(existing)

    await db.refresh(contribution)
    return ContributionOut.model_validate(contribution)
