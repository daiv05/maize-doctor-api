from datetime import datetime

from app.schemas.base import CamelModel


class ContributionOut(CamelModel):
    id: str
    client_id: str
    label: str
    status: str
    created_at: datetime
