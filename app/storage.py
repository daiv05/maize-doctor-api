import io
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import settings


class InvalidImageError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


async def save_upload_image(upload: UploadFile, subdir: str) -> str:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    contents = await upload.read()
    if len(contents) > max_bytes:
        raise FileTooLargeError(f"File exceeds {settings.max_upload_size_mb}MB limit")

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("Uploaded file is not a valid image") from exc

    extension = Path(upload.filename or "").suffix or ".jpg"
    filename = f"{uuid.uuid4()}{extension}"
    target_dir = Path(settings.upload_dir) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_bytes(contents)

    return str(target_path)
