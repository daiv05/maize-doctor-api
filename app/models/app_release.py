import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppRelease(Base):
    __tablename__ = "app_releases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    version_name: Mapped[str] = mapped_column(String(30), nullable=False)
    min_supported_version_code: Mapped[int] = mapped_column(Integer, nullable=False)
    download_url: Mapped[str] = mapped_column(String(500), nullable=False)
    release_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
