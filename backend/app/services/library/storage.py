"""File storage, hashing, and upload validation."""
import hashlib
import shutil
import uuid
from pathlib import Path

from app.core.config import get_settings

_settings = get_settings()

# LIB-UI-02 — PDF, DOCX, PPTX and image formats.
ALLOWED_EXTENSIONS: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".tiff": {"image/tiff"},
    ".tif": {"image/tiff"},
}


class UploadRejected(Exception):
    """Raised when a file fails validation. Surfaces as HTTP 400."""


def documents_dir() -> Path:
    path = Path(_settings.LIBRARY_STORAGE_DIR) / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def images_dir(document_id: uuid.UUID | str) -> Path:
    """LIB-IDX-02 — per-document image directory. Images live here on disk and
    are referenced from chunks by path, never embedded as pixel data."""
    path = Path(_settings.LIBRARY_STORAGE_DIR) / "images" / str(document_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_upload(filename: str, content_type: str, size: int) -> str:
    """Check extension, MIME type and size. Returns the normalised extension."""
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UploadRejected(f"Unsupported file type '{ext}'. Allowed: {allowed}")

    # Browsers are inconsistent about MIME for Office formats, so a mismatch is
    # not fatal — the extension is authoritative and parsing will fail loudly
    # on a genuinely malformed file.
    if size > _settings.max_upload_bytes:
        mb = size / 1024 / 1024
        raise UploadRejected(f"File is {mb:.1f} MB; the limit is {_settings.MAX_UPLOAD_MB} MB.")

    if size == 0:
        raise UploadRejected("File is empty.")

    return ext


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def save_upload(data: bytes, original_name: str, document_id: uuid.UUID) -> Path:
    """Write bytes under a UUID-derived name.

    The client-supplied filename is only ever used for its extension, so a
    crafted name like ``../../etc/passwd`` cannot escape the storage dir.
    """
    ext = Path(original_name).suffix.lower()
    dest = documents_dir() / f"{document_id}{ext}"
    dest.write_bytes(data)
    return dest


def delete_document_files(stored_path: str, document_id: uuid.UUID | str) -> None:
    """Remove a document's file and its image directory. Missing files are not
    an error — deletion should be idempotent."""
    path = Path(stored_path)
    if path.exists():
        path.unlink()

    img_dir = Path(_settings.LIBRARY_STORAGE_DIR) / "images" / str(document_id)
    if img_dir.exists():
        shutil.rmtree(img_dir, ignore_errors=True)


def relative_path(path: Path | str) -> str:
    """Storage-relative path for API responses, so absolute container paths
    never leak to clients."""
    try:
        return str(Path(path).relative_to(Path(_settings.LIBRARY_STORAGE_DIR))).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")
