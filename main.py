# main.py

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware

# Import from your separated WBS modules
from section_2_1_ingestion import extract_pdf_pages
from section_2_2_chunking import (
    detect_section_boundaries,
    group_pages_by_section,
    chunk_text_by_tokens,
    generate_mock_embedding
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/tender")
async def tender(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    # WBS 2.1.1 Validation
    if file.filename is None or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file is required")

    content = await file.read()
    if len(content) > 104857600:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 100MB.")

    # Save to Section 1 DB
    new_tender = MockTender(filename=file.filename, user_id=current_user["id"])
    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    # Execute Section 2.1 Pipeline
    page_data = extract_pdf_pages(file_content=content, tender_id=new_tender.id)

    # Execute Section 2.2 Pipeline
    page_data = detect_section_boundaries(page_data)
    section_groups = group_pages_by_section(page_data)

    total_chunks_processed = 0

    for group in section_groups:
        text_chunks = chunk_text_by_tokens(group["text"], max_tokens=2000)

        for index, text_chunk in enumerate(text_chunks):
            embedding_vector = generate_mock_embedding(text_chunk)
            page_range_str = f"{group['start_page']}-{group['end_page']}" if group['start_page'] != group[
                'end_page'] else str(group['start_page'])

            # WBS 2.2.3 & 2.2.5
            new_chunk = MockChunk(
                tender_id=group["tender_id"],
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

    return {
        "message": "Tender ingested and section-chunked successfully",
        "tender_id": new_tender.id,
        "total_pages": len(page_data),
        "total_sections_found": len(section_groups),
        "total_chunks": total_chunks_processed
    }