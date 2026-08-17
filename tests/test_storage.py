import io

import pytest
from fastapi import UploadFile
from PIL import Image

from app.config import settings
from app.storage import FileTooLargeError, InvalidImageError, save_upload_image


def _make_png_upload(filename: str = "leaf.png") -> UploadFile:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buffer, format="PNG")
    buffer.seek(0)
    return UploadFile(filename=filename, file=buffer)


@pytest.mark.asyncio
async def test_save_valid_image_returns_path_and_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = _make_png_upload()

    path = await save_upload_image(upload, subdir="dataset-contributions")

    assert path.endswith(".png")
    assert (tmp_path / "dataset-contributions").exists()


@pytest.mark.asyncio
async def test_extension_comes_from_detected_format_not_filename(tmp_path, monkeypatch):
    """The saved extension must be derived from PIL's detected format, never
    from the attacker-controlled (and unbounded) client filename."""
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = _make_png_upload(filename="../payload" + "x" * 600 + ".exe")

    path = await save_upload_image(upload, subdir="dataset-contributions")

    assert path.endswith(".png")
    assert "payload" not in path


@pytest.mark.asyncio
async def test_corrupt_image_raises_invalid_image_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = UploadFile(filename="broken.png", file=io.BytesIO(b"not a real image"))

    with pytest.raises(InvalidImageError):
        await save_upload_image(upload, subdir="dataset-contributions")


@pytest.mark.asyncio
async def test_declared_size_over_limit_is_rejected_before_reading(tmp_path, monkeypatch):
    """The part's declared size is checked first, so an oversized body is never
    materialized in memory. The payload here is tiny, so only that early check
    can raise."""
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="green").save(buffer, format="PNG")
    buffer.seek(0)
    upload = UploadFile(
        filename="huge.png", file=buffer, size=settings.max_upload_size_mb * 1024 * 1024 + 1
    )

    with pytest.raises(FileTooLargeError):
        await save_upload_image(upload, subdir="dataset-contributions")


@pytest.mark.asyncio
async def test_oversized_image_raises_file_too_large_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    monkeypatch.setattr("app.storage.settings.max_upload_size_mb", 0)
    upload = _make_png_upload()

    with pytest.raises(FileTooLargeError):
        await save_upload_image(upload, subdir="dataset-contributions")
