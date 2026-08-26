from pydantic import Field

from app.schemas.base import CamelModel


class AppVersionOut(CamelModel):
    latest_version_code: int
    latest_version_name: str
    min_supported_version_code: int
    force_update: bool
    download_url: str
    release_notes: str | None


class AppReleaseIn(CamelModel):
    platform: str = Field(pattern="^(android|ios)$")
    version_code: int = Field(ge=1)
    version_name: str = Field(min_length=1, max_length=30)
    min_supported_version_code: int = Field(ge=1)
    download_url: str = Field(min_length=1, max_length=500, pattern=r"^https://")
    release_notes: str | None = Field(default=None, max_length=2000)


class AppReleaseOut(CamelModel):
    id: str
    platform: str
    version_code: int
    version_name: str
    min_supported_version_code: int
    download_url: str
    release_notes: str | None
