from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel


class CorrectionIn(CamelModel):
    client_id: str = Field(max_length=36)
    scan_id: str = Field(max_length=36)
    observed_label: str = Field(max_length=64)
    note: str | None = Field(default=None, max_length=1000)
    status: Literal["pending", "reviewed"] = "pending"
    created_at: datetime


class CorrectionOut(CamelModel):
    id: str
    client_id: str
    status: str
    created_at: datetime
