"""
Task 2.1.1 - Tender/RFP PDF upload endpoint (validation + save-to-disk half)
Linked requirement: TN-ING-01

Named tender_storage.py (not storage.py) since the Evidence Library
(Task 6.2.2) will need its own drag-and-drop upload storage later for
PDF/DOCX/PPTX/images - keeping these separate avoids one grab-bag module
two unrelated features both depend on.

In this merged backend that separation is already real: the library's own
storage lives at app/services/library/storage.py and writes under
LIBRARY_STORAGE_DIR, while this one writes under TENDER_STORAGE_DIR. Do not
merge them.
"""
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings

MAX_TENDER_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB, per TN-ING-01
# 500+ pages is a *content* requirement (handled by extraction just reading
# however many pages exist), not a separate check here - PyMuPDF has no
# fixed page ceiling, only the 100MB file-size limit is actually enforced
# at upload time.


def validate_tender_upload(file: UploadFile, content: bytes) -> None:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A PDF file is required.")

    if len(content) > MAX_TENDER_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_TENDER_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
        )

    if len(content) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")


def save_tender_file(tender_id: uuid.UUID, original_filename: str, content: bytes) -> str:
    """Saves under STORAGE_ROOT/tenders/{tender_id}/{original_filename} and
    returns the path stored on the Tender row. Keyed by tender_id (not just
    the raw filename) so two uploads named "RFP.pdf" never collide."""
    settings = get_settings()
    tender_dir = Path(settings.TENDER_STORAGE_DIR) / str(tender_id)
    tender_dir.mkdir(parents=True, exist_ok=True)

    file_path = tender_dir / Path(original_filename).name
    file_path.write_bytes(content)
    return str(file_path)
