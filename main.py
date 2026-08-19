import os
from io import BytesIO

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from mock_section_1 import MockTender, MockChunk, get_current_user, get_db, DB_CHUNKS
from section_2_1_ingestion import extract_pdf_pages
from section_2_2_chunking import detect_section_boundaries, group_pages_by_section, chunk_text_by_tokens, \
    generate_mock_embedding
from section_3_extraction import extract_all_chunks_parallel, assemble_master_table

app = FastAPI()

# allow_origins=["*"] + allow_credentials=True is invalid per the CORS spec
# (browsers reject a wildcard origin on credentialed requests) and, where it
# is honored, effectively lets any website make authenticated calls against
# this API. Set ALLOWED_ORIGINS to a comma-separated list of your real
# frontend origin(s) in the environment; defaults to local dev only.
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 104857600  # 100 MB

# /extract and /export/excel each independently re-ran the full (expensive,
# non-deterministic) LLM extraction against the same chunks -> double API
# cost, and a real risk that what a user previewed via /extract doesn't match
# what actually ends up in the downloaded Excel file. This in-memory cache
# makes the second call reuse the first call's results. Swap it for a
# persistent results table if you need it to survive a restart or be shared
# across multiple worker processes.
_extraction_cache = {}


def _process_pdf_sync(content: bytes, tender_id: int):
    """CPU-bound work (PDF parsing, OCR, section detection, tokenizing) that
    must not run directly on the event loop -- see _process_pdf_sync usage
    below via run_in_threadpool."""
    page_data = extract_pdf_pages(file_content=content, tender_id=tender_id)
    page_data = detect_section_boundaries(page_data)
    section_groups = group_pages_by_section(page_data)

    chunked_groups = []
    for group in section_groups:
        text_chunks = chunk_text_by_tokens(text=group["text"], max_tokens=1000, overlap_tokens=100)
        chunked_groups.append((group, text_chunks))

    return page_data, section_groups, chunked_groups


async def _get_or_run_extraction(tender_id: int) -> dict:
    if tender_id in _extraction_cache:
        return _extraction_cache[tender_id]

    real_db_chunks = [chunk for chunk in DB_CHUNKS if chunk.tender_id == tender_id]
    if not real_db_chunks:
        raise HTTPException(status_code=404, detail="No chunks found")

    chunk_dicts = [{"text": c.text, "page_range": c.page_range, "section": c.section} for c in real_db_chunks]
    all_chunk_results = await extract_all_chunks_parallel(chunk_dicts, max_concurrent_calls=3)
    master_table_data = assemble_master_table(all_chunk_results)

    _extraction_cache[tender_id] = master_table_data
    return master_table_data


@app.post("/tender")
async def ingest_tender(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    # .endswith(".pdf") rejected legitimate files like "Tender.PDF".
    if file.filename is None or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF required")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    # A non-PDF file renamed to .pdf previously reached fitz.open() and blew
    # up with an unhandled 500 deep inside the ingestion pipeline.
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not appear to be a valid PDF")

    new_tender = MockTender(filename=file.filename, user_id=current_user["id"])
    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    try:
        # extract_pdf_pages() (PyMuPDF parsing + Tesseract OCR) and the
        # tokenizing/section-detection pass are all CPU-bound and previously
        # ran directly on the event loop, blocking every other request for
        # the full duration of a large/scanned tender. Offload to a thread.
        page_data, section_groups, chunked_groups = await run_in_threadpool(
            _process_pdf_sync, content, new_tender.id
        )

        total_chunks_processed = 0
        for group, text_chunks in chunked_groups:
            for index, text_chunk in enumerate(text_chunks):
                embedding_vector = generate_mock_embedding(text_chunk)
                page_range_str = f"{group['start_page']}-{group['end_page']}" if group['start_page'] != group[
                    'end_page'] else str(group['start_page'])

                new_chunk = MockChunk(
                    tender_id=new_tender.id,
                    page_range=page_range_str,
                    section=group["section"],
                    chunk_index=index,
                    text=text_chunk,
                    embedding=embedding_vector
                )
                db.add(new_chunk)
                total_chunks_processed += 1

        new_tender.status = "Indexed"
        db.commit()

    except Exception as exc:
        # Previously: an ingestion failure left the tender row already
        # committed with no chunks and no "Failed" status, plus an unhandled
        # 500 with a raw stack trace. Now the record reflects reality and the
        # caller gets a clean 422.
        try:
            db.rollback()
        except Exception:
            pass
        new_tender.status = "Failed"
        try:
            db.commit()
        except Exception:
            pass
        print(f"[X] Ingestion failed for tender {new_tender.id}: {exc}")
        raise HTTPException(status_code=422, detail=f"Failed to process PDF: {exc}")

    return {
        "message": "Stage 1 Complete: Tender ingested and chunked successfully.",
        "tender_id": new_tender.id,
        "total_pages": len(page_data),
        "total_sections_found": len(section_groups),
        "total_chunks_generated": total_chunks_processed
    }


@app.post("/extract/{tender_id}")
async def extract_requirements(
        tender_id: int,  # was `float` -> "/extract/5" parsed as 5.0 and leaked into responses
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    master_table_data = await _get_or_run_extraction(tender_id)

    return {
        "tender_id": tender_id,
        "extraction_summary": master_table_data
    }


@app.get("/export/excel/{tender_id}")
async def export_excel(
        tender_id: int,  # was `float` -> filenames came out as "tender_5.0_requirements.xlsx"
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    master_table_data = await _get_or_run_extraction(tender_id)

    rename_map = {
        "page": "Page",
        "section_name": "Section Name",
        "responsibility": "Responsibility",
        "reference_number": "Reference Number",
        "clause_requirement_description": "Clause / Requirement Description",
        "mandatory": "Mandatory",
        "evaluation_impact": "Evaluation Impact (Pass/Fail / Score)",
        "dpl": "DPL",
        "prime": "PRIME",
        "the_t": "The T...",
        "joint_responsibility": "Joint Responsibility",
        "evidence_document_required": "Evidence / Document Required",
        "remarks": "Remarks"
    }

    if master_table_data["master_table"]:
        df = pd.DataFrame(master_table_data["master_table"])
    else:
        # pd.DataFrame([]) has no columns at all, so a zero-result tender
        # previously downloaded as a totally blank file with no headers.
        df = pd.DataFrame(columns=list(rename_map.keys()))

    df.rename(columns=rename_map, inplace=True)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Tasks & Responsibility")

        # Chunks that failed extraction after 3 retries were silently dropped
        # -- the only trace of them was a count in the /extract JSON, invisible
        # in the actual Excel deliverable. Surface them on their own sheet.
        review_rows = master_table_data.get("review_data", [])
        if review_rows:
            review_df = pd.DataFrame([
                {
                    "Page Range": r.get("page_range"),
                    "Section": r.get("section"),
                    "Raw Text (unparsed)": r.get("raw_failed_text"),
                }
                for r in review_rows
            ])
            review_df.to_excel(writer, index=False, sheet_name="Needs Manual Review")

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=tender_{tender_id}_requirements.xlsx"}
    )