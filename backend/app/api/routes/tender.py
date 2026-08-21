"""
Real tender ingestion endpoint — WBS 2.1 + 2.2 + 3.1, replacing Shaheer's
mock prototype (section2.py). Uses the actual DB session, actual auth
dependency, and actual Tender/TenderChunk/Requirement models — nothing
here is discarded or faked.

This is registered as POST /api/tenders/upload — distinct from the
existing POST /api/tenders in tenders.py, which stays as the lightweight
stub Task 7 uses to test progress tracking without a real file.

Wired into Task 7's progress tracker (app.services.progress) at every
stage transition. Upload -> Parse -> Chunk -> Extract all happen in this
one request now (Task 3.1's real LLM extraction, adapted from Shaheer's
section_3_extraction.py) - a client watching this tender's WebSocket sees
the full real pipeline live, including requirements_extracted ticking up
per chunk during extraction.
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.enums import TenderStatus
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.models.user import User
from app.services.pdf_extraction import extract_pdf_pages
from app.services.chunking import (
    chunk_sectioned_pages,
    detect_section_boundaries,
    guard_against_whole_document_ingestion,
)
from app.services.extraction import run_extraction
from app.services.matching import run_matching
from app.services.scoring import run_scoring
from app.services.output_assembly import run_output_assembly
from app.services.progress import publish_progress

router = APIRouter(prefix="/api/tenders", tags=["tenders"])

MAX_FILE_SIZE_BYTES = 104857600  # 100MB


@router.post("/upload")
async def upload_tender(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 2.1.1 — validation
    if file.filename is None or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file is required")

    declared_size = file.size if hasattr(file, "size") else None
    if declared_size and declared_size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 100MB.")

    content = await file.read()

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 100MB.")

    # Save the file to disk for real — the previous prototype never did
    # this, but Tender.file_path is a required (non-nullable) column.
    settings = get_settings()
    storage_dir = Path(settings.TENDER_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)

    tender_id = uuid.uuid4()
    saved_filename = f"{tender_id}_{file.filename}"
    saved_path = storage_dir / saved_filename
    saved_path.write_bytes(content)

    new_tender = Tender(
        id=tender_id,
        name=file.filename,
        original_filename=file.filename,
        file_path=str(saved_path),
        file_size_bytes=len(content),
        uploaded_by=current_user.id,
        status=TenderStatus.PARSING,
    )
    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    # First progress event — a client connecting right after upload should
    # immediately see "parsing", not silence.
    publish_progress(str(tender_id), TenderStatus.PARSING, message="Extracting pages from PDF")

    try:
        # 2.1.2 / 2.1.3 — real extraction, reused from Shaheer's approach
        pages = extract_pdf_pages(content)

        if not pages:
            new_tender.status = TenderStatus.FAILED
            new_tender.progress_message = "No pages could be extracted from this PDF."
            db.commit()
            publish_progress(
                str(tender_id), TenderStatus.FAILED,
                message="No pages could be extracted from this PDF.",
            )
            raise HTTPException(status_code=422, detail="No pages could be extracted from this PDF.")

        new_tender.status = TenderStatus.CHUNKING
        new_tender.page_count = len(pages)
        db.commit()
        publish_progress(
            str(tender_id), TenderStatus.CHUNKING,
            message=f"Extracted {len(pages)} pages — detecting sections",
        )

        # 2.2 — section-aware chunking
        sectioned_pages = detect_section_boundaries(pages)
        chunk_results = chunk_sectioned_pages(sectioned_pages)

        try:
            guard_against_whole_document_ingestion(chunk_results)
        except ValueError as exc:
            new_tender.status = TenderStatus.FAILED
            new_tender.progress_message = str(exc)
            db.commit()
            publish_progress(str(tender_id), TenderStatus.FAILED, message=str(exc))
            raise HTTPException(status_code=422, detail=str(exc))

        for cr in chunk_results:
            db.add(
                TenderChunk(
                    tender_id=new_tender.id,
                    chunk_index=cr.chunk_index,
                    section=cr.section,
                    page_start=cr.page_start,
                    page_end=cr.page_end,
                    content=cr.text,
                    token_count=cr.token_count,
                    overlap_tokens=cr.overlap_tokens,
                )
            )

        db.commit()
        publish_progress(
            str(tender_id), TenderStatus.CHUNKING,
            percent=33,
            message=f"Chunked into {len(chunk_results)} sections — starting extraction",
        )

        # 3.1 — real requirement extraction (Shaheer's LLM pipeline, wired in)
        db.refresh(new_tender)
        extraction_result = await run_extraction(db, new_tender)

        new_tender.status = TenderStatus.MERGING  # extraction+dedup done
        db.commit()

        # 3.3 — running tally vs. evaluation weighting + coverage reconciliation (Task 3)
        scoring_result = run_scoring(db, new_tender)
        publish_progress(
            str(tender_id), TenderStatus.MERGING,
            percent=60,
            message=(
                f"Extraction complete: {extraction_result['created']} requirements found, "
                f"{extraction_result['failed_chunks']} chunk(s) need manual review — "
                f"coverage {scoring_result['coverage_percent']}%"
                if scoring_result["coverage_percent"] is not None
                else f"Extraction complete: {extraction_result['created']} requirements found"
            ),
            extracted_requirements_count=extraction_result["created"],
        )

        # 4.1/4.2 — real evidence matching against the Evidence Library (Task 4)
        db.refresh(new_tender)
        matching_result = run_matching(db, new_tender)

        # 5.1/5.2/5.3 — real output assembly: Excel tracker, folder + zip,
        # optional summary report (Task 5). Produces a first draft package;
        # /finalize (Task 5's output.py router) re-runs this after a sales
        # manager reviews matches, so the delivered zip matches their choices.
        db.refresh(new_tender)
        assembly_result = run_output_assembly(db, new_tender)

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        new_tender.status = TenderStatus.FAILED
        db.commit()
        publish_progress(str(tender_id), TenderStatus.FAILED, message="Failed to process tender document.")
        raise HTTPException(status_code=500, detail="Failed to process tender document.")

    return {
        "message": "Extracted, chunked, requirements identified, evidence matched, and output assembled",
        "tender_id": new_tender.id,
        "total_pages": len(pages),
        "total_chunks": len(chunk_results),
        "requirements_found": extraction_result["created"],
        "failed_chunks": extraction_result["failed_chunks"],
        "evidence_matched": matching_result["matched"],
        "evidence_missing": matching_result["missing"],
        "output_zip_path": assembly_result["output_zip_path"],
    }