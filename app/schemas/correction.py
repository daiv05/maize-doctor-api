from datetime import datetime

from app.schemas.base import CamelModel


class CorrectionIn(CamelModel):
    client_id: str
    scan_id: str
    observed_label: str
    note: str | None = None
    status: str = "pending"
    created_at: datetime


class CorrectionOut(CamelModel):
    id: str
    client_id: str
    status: str
    created_at: datetime
