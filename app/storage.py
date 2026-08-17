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


_EXTENSION_BY_FORMAT = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
    "GIF": ".gif",
    "BMP": ".bmp",
    "TIFF": ".tif",
}


def _extension_for(image_format: str | None) -> str:
    """
    Maps a PIL-detected image format to the extension the file is saved under.

    @param {str|None} image_format Format reported by PIL, never client-supplied.
    @returns {str} Lowercase extension including the leading dot.
    @throws {InvalidImageError} If PIL could not identify the format.
    """
    if not image_format:
        raise InvalidImageError("Uploaded file is not a valid image")
    return _EXTENSION_BY_FORMAT.get(image_format, f".{image_format.lower()}")


async def save_upload_image(upload: UploadFile, subdir: str) -> str:
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if upload.size is not None and upload.size > max_bytes:
        raise FileTooLargeError(f"File exceeds {settings.max_upload_size_mb}MB limit")

    contents = await upload.read()
    if len(contents) > max_bytes:
        raise FileTooLargeError(f"File exceeds {settings.max_upload_size_mb}MB limit")

    try:
        with Image.open(io.BytesIO(contents)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("Uploaded file is not a valid image") from exc

    filename = f"{uuid.uuid4()}{_extension_for(image_format)}"
    target_dir = Path(settings.upload_dir) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename
    target_path.write_bytes(contents)

    return str(target_path)
