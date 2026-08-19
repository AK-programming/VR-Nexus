"""
Task 2.1 - Upload Handling
Task 2.2 - Section-Aware Chunking
Linked requirements: TN-ING-01..06

This replaces Shaheer's standalone prototype (main.py / MockTender /
MockSession / hardcoded get_current_user). Same pipeline shape - upload,
extract, detect sections, chunk - but every piece now goes through the
real app: app.api.deps.get_current_user (Task 1.2.4) instead of a fake
dict, app.core.database.get_db (Task 1.1) instead of a MockSession whose
.commit() was a no-op, and the real Tender/TenderChunk models instead of
mock classes - so what this endpoint reports actually persisted.

Runs synchronously within the request for now (no Celery worker for Stage
1 yet), but every state change goes through publish_progress() so the
WebSocket route (Task 7.1) and a future Celery-based version can share
the exact same progress semantics.
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enums import TenderStatus
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.models.user import User
from app.schemas.tender import TenderOut, TenderUploadResponse
from app.services.chunking import (
    chunk_sectioned_pages,
    detect_section_boundaries,
    guard_against_whole_document_ingestion,
)
from app.services.pdf_extraction import extract_pdf_pages
from app.services.progress import publish_progress
from app.services.tender_storage import save_tender_file, validate_tender_upload

router = APIRouter(prefix="/api/tenders", tags=["tenders"])


@router.post("", response_model=TenderUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_tender(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderUploadResponse:
    content = await file.read()

    # --- 2.1.1: validate ---
    validate_tender_upload(file, content)

    # Create the Tender row first so its id can be used for the storage
    # path and every progress event, even though page_count etc. aren't
    # known until after extraction.
    tender = Tender(
        name=file.filename,
        original_filename=file.filename,
        file_path="",  # filled in right below
        file_size_bytes=len(content),
        status=TenderStatus.UPLOADED,
        uploaded_by=current_user.id,
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)

    file_path = save_tender_file(tender.id, file.filename, content)
    tender.file_path = file_path
    db.commit()

    publish_progress(str(tender.id), TenderStatus.UPLOADED, message="File received and saved.")

    try:
        # --- 2.1.2 / 2.1.3: extract text (+ tables) per page, OCR fallback ---
        publish_progress(str(tender.id), TenderStatus.PARSING, message="Extracting text and tables per page.")
        pages = extract_pdf_pages(content)
        if not pages:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="PDF has no pages.")

        # --- 2.2.1 / 2.2.2 / 2.2.3: detect sections, chunk with overlap ---
        publish_progress(
            str(tender.id), TenderStatus.CHUNKING, message=f"Detecting sections across {len(pages)} pages."
        )
        sectioned_pages = detect_section_boundaries(pages)
        chunks = chunk_sectioned_pages(sectioned_pages)

        # --- 2.2.4: guard before anything downstream could touch this ---
        guard_against_whole_document_ingestion(chunks)

        for text_chunk in chunks:
            db.add(
                TenderChunk(
                    tender_id=tender.id,
                    chunk_index=text_chunk.chunk_index,
                    section=text_chunk.section,
                    page_start=text_chunk.page_start,
                    page_end=text_chunk.page_end,
                    content=text_chunk.text,
                    token_count=text_chunk.token_count,
                    overlap_tokens=text_chunk.overlap_tokens,
                )
            )

        tender.page_count = len(pages)
        tender.status = TenderStatus.CHUNKING
        tender.progress_percent = 33
        tender.progress_message = (
            f"Chunking complete: {len(chunks)} chunks across "
            f"{len({p.section for p in sectioned_pages})} section(s). "
            "Ready for Stage 2 (requirement extraction - not yet built, Task 3.1)."
        )
        db.commit()

        progress_payload = publish_progress(
            str(tender.id),
            TenderStatus.CHUNKING,
            percent=33,
            message=tender.progress_message,
        )

        return TenderUploadResponse(
            id=tender.id,
            name=tender.name,
            original_filename=tender.original_filename,
            page_count=tender.page_count,
            status=tender.status,
            progress_percent=progress_payload["percent_complete"],
            total_chunks=len(chunks),
            sections_detected=sorted({c.section for c in chunks}),
            created_at=tender.created_at,
        )

    except HTTPException:
        tender.status = TenderStatus.FAILED
        db.commit()
        publish_progress(str(tender.id), TenderStatus.FAILED, message="Upload/processing failed.")
        raise
    except Exception as exc:  # noqa: BLE001 - want to record failure state either way
        tender.status = TenderStatus.FAILED
        db.commit()
        publish_progress(str(tender.id), TenderStatus.FAILED, message=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Tender processing failed: {exc}"
        ) from exc


@router.get("/{tender_id}", response_model=TenderOut)
def get_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tender not found.")
    return tender
