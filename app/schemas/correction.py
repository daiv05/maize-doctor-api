from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.constants import DIAGNOSIS_LABELS
from app.schemas.base import CamelModel


class CorrectionIn(CamelModel):
    client_id: str = Field(max_length=36)
    scan_id: str = Field(max_length=36)
    observed_label: str = Field(max_length=64)
    note: str | None = Field(default=None, max_length=1000)
    status: Literal["pending", "reviewed"] = "pending"
    created_at: datetime

    @field_validator("observed_label")
    @classmethod
    def _validate_observed_label(cls, value: str) -> str:
        if value not in DIAGNOSIS_LABELS:
            raise ValueError(f"observed_label debe ser uno de: {DIAGNOSIS_LABELS}")
        return value


class CorrectionOut(CamelModel):
    id: str
    client_id: str
    status: str
    created_at: datetime
