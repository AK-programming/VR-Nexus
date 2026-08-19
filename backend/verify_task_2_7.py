"""
Run this AFTER `alembic upgrade head` to confirm Task 2.1 (Upload Handling),
2.2 (Section-Aware Chunking), and 7.1 (Live Progress Streaming) actually
work end-to-end on your machine: builds a small real PDF, runs it through
extraction -> section detection -> chunking -> the guard, inserts a real
Tender + TenderChunk rows, publishes a progress event over Redis, then
cleans up everything it created.

Usage (from the backend/ folder, with the venv active):
    python verify_task_2_7.py
"""
import sys
import uuid

import fitz
from sqlalchemy import inspect

from app.core.database import SessionLocal, engine
from app.models import Tender, TenderChunk
from app.models.enums import TenderStatus
from app.services.chunking import (
    chunk_sectioned_pages,
    detect_section_boundaries,
    guard_against_whole_document_ingestion,
)
from app.services.pdf_extraction import extract_pdf_pages
from app.services.progress import get_latest_progress, publish_progress

EXPECTED_NEW_TENDER_COLUMNS = {"progress_percent", "progress_message", "extracted_requirements_count"}


def build_test_pdf() -> bytes:
    """A tiny 2-page, 2-section PDF, built with PyMuPDF directly so this
    script needs no extra dependency beyond what's already installed."""
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((50, 72), "Specific Procurement Notice (SPN)\n" + ("Bidders must submit sealed proposals. " * 60))
    page2 = doc.new_page()
    page2.insert_text((50, 72), "Evaluation Criteria\n" + ("70% Technical, 30% Financial weighting applies. " * 60))
    content = doc.tobytes()
    doc.close()
    return content


def main() -> int:
    print("=== Task 2.1 / 2.2 / 7.1 verification ===\n")

    # --- 1. Schema check ---
    print("[1/5] Checking database schema...")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "tender_chunks" not in tables:
        print("  FAIL: 'tender_chunks' table not found. Did you run `alembic upgrade head`?")
        return 1
    tender_columns = {c["name"] for c in inspector.get_columns("tenders")}
    missing = EXPECTED_NEW_TENDER_COLUMNS - tender_columns
    if missing:
        print(f"  FAIL: tenders table is missing columns {missing}. Run `alembic upgrade head`.")
        return 1
    print("  OK: tender_chunks table present, tenders has the new progress columns.\n")

    # --- 2. Extraction + section detection + chunking + guard ---
    print("[2/5] Running extraction -> section detection -> chunking -> guard...")
    content = build_test_pdf()
    pages = extract_pdf_pages(content)
    assert len(pages) == 2, f"expected 2 pages, got {len(pages)}"
    sectioned = detect_section_boundaries(pages)
    assert sectioned[0].section == "SPN", f"expected page 1 section=SPN, got {sectioned[0].section}"
    assert sectioned[1].section == "Evaluation Criteria", f"expected page 2 section=Evaluation Criteria, got {sectioned[1].section}"
    chunks = chunk_sectioned_pages(sectioned)
    guard_against_whole_document_ingestion(chunks)
    print(f"  OK: {len(pages)} pages extracted, {len(chunks)} chunk(s) produced, guard passed.\n")

    # --- 3. Real DB round-trip ---
    print("[3/5] Inserting real Tender + TenderChunk rows...")
    db = SessionLocal()
    tender_id = None
    try:
        tender = Tender(
            name="verify_task_2_7 test tender",
            original_filename="verify_task_2_7.pdf",
            file_path="/tmp/verify_task_2_7.pdf",
            page_count=len(pages),
            status=TenderStatus.CHUNKING,
            progress_percent=33,
        )
        db.add(tender)
        db.commit()
        db.refresh(tender)
        tender_id = tender.id

        for c in chunks:
            db.add(
                TenderChunk(
                    tender_id=tender.id,
                    chunk_index=c.chunk_index,
                    section=c.section,
                    page_start=c.page_start,
                    page_end=c.page_end,
                    content=c.text,
                    token_count=c.token_count,
                    overlap_tokens=c.overlap_tokens,
                )
            )
        db.commit()

        stored_count = db.query(TenderChunk).filter(TenderChunk.tender_id == tender.id).count()
        assert stored_count == len(chunks), f"expected {len(chunks)} stored chunks, found {stored_count}"
        print(f"  OK: Tender {tender.id} and {stored_count} TenderChunk row(s) really persisted.\n")
    finally:
        if tender_id is not None:
            db.query(TenderChunk).filter(TenderChunk.tender_id == tender_id).delete()
            db.query(Tender).filter(Tender.id == tender_id).delete()
            db.commit()
        db.close()
    print("[4/5] Test data cleaned up.\n")

    # --- 5. Redis / progress streaming check ---
    print("[5/5] Checking Redis-backed progress streaming (Task 7.1)...")
    test_id = str(uuid.uuid4())
    try:
        publish_progress(test_id, TenderStatus.PARSING, message="verify_task_2_7 test event")
        latest = get_latest_progress(test_id)
        assert latest is not None and latest["status"] == "parsing"
        print("  OK: connected to Redis, published and read back a progress payload.")
        print(f"       payload: {latest}\n")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: could not reach Redis at the REDIS_URL in your .env ({exc}).")
        print("        Task 7.1's WebSocket progress won't work until Redis is running.")
        print("        See README.md for the Windows Redis setup step.\n")
        return 1

    print("Task 2.1 / 2.2 / 7.1 verified successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
