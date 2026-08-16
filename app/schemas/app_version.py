from app.schemas.base import CamelModel


class AppVersionOut(CamelModel):
    latest_version_code: int
    latest_version_name: str
    min_supported_version_code: int
    force_update: bool
    download_url: str
    release_notes: str | None
