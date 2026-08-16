import io

import pytest
from fastapi import UploadFile
from PIL import Image

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
async def test_corrupt_image_raises_invalid_image_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    upload = UploadFile(filename="broken.png", file=io.BytesIO(b"not a real image"))

    with pytest.raises(InvalidImageError):
        await save_upload_image(upload, subdir="dataset-contributions")


@pytest.mark.asyncio
async def test_oversized_image_raises_file_too_large_error(tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    monkeypatch.setattr("app.storage.settings.max_upload_size_mb", 0)
    upload = _make_png_upload()

    with pytest.raises(FileTooLargeError):
        await save_upload_image(upload, subdir="dataset-contributions")
