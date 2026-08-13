"""Evidence Library REST endpoints (WBS 6.2).

Upload and Train are separate calls on purpose (LIB-UI-04/06): the duplicate
check has to happen *before* anything is parsed or embedded, so uploading only
stores and fingerprints the file, and Train is what spends the CPU.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import Principal, current_user
from app.config import settings
from app.db import get_db
from app.models import (
    STAGE_LABELS,
    Chunk,
    Document,
    DocumentCategory,
    DocumentFileType,
    DocumentTrainingStatus,
    IndexJob,
    JobStage,
)
from app.schemas import (
    AnswerOut,
    AskRequest,
    DocumentDetailOut,
    DocumentOut,
    DuplicateCheckResult,
    JobOut,
    SearchResponse,
    TrainRequest,
    TrainResponse,
    UploadResponse,
)
from app.services import rag, search, storage
from app.services.parsers import extract as extract_mod
from app.tasks import indexing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/library", tags=["library"])

# Stages where a worker already holds the document. Queueing a second job for
# one of these would race the first over the same chunk rows. 1.1.2 folds the
# pipeline stages into training_status, so "busy" is a set, not one value.
_IN_FLIGHT = {
    DocumentTrainingStatus.PARSING,
    DocumentTrainingStatus.TAGGING,
    DocumentTrainingStatus.EMBEDDING,
}

# 1.1.2 stores file_type as a NOT NULL enum, so it has to be resolved at upload.
# storage.validate_upload has already rejected anything not in this map.
_FILE_TYPES = {
    ".pdf": DocumentFileType.PDF,
    ".docx": DocumentFileType.DOCX,
    ".pptx": DocumentFileType.PPTX,
    ".png": DocumentFileType.IMAGE,
    ".jpg": DocumentFileType.IMAGE,
    ".jpeg": DocumentFileType.IMAGE,
    ".tiff": DocumentFileType.IMAGE,
    ".tif": DocumentFileType.IMAGE,
}


def _file_type_of(filename: str) -> DocumentFileType:
    return _FILE_TYPES.get(Path(filename).suffix.lower(), DocumentFileType.IMAGE)


def _get_document(db: Session, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


# ---------------------------------------------------------------------------
# Upload (LIB-UI-01, LIB-UI-02, LIB-UI-03, LIB-UI-06)
# ---------------------------------------------------------------------------

@router.post("/{category}/upload", response_model=UploadResponse, status_code=201)
async def upload_document(
    category: DocumentCategory,
    file: UploadFile = File(...),
    title: str = Form(""),
    client: str = Form(""),
    sector: str = Form(""),
    service_line: str = Form(""),
    geography: str = Form(""),
    keywords: str = Form(""),
    doc_type: str = Form(""),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> UploadResponse:
    """Store one file in a category and report any duplicate warning.

    The category is in the path, which is what gives each of the three tabs its
    own upload endpoint (LIB-UI-01). Nothing is parsed or embedded here — that is
    Train's job.
    """
    data = await file.read()

    try:
        storage.validate_upload(file.filename or "", file.content_type or "", len(data))
    except storage.UploadRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    content_hash = storage.hash_bytes(data)

    # LIB-UI-06 — checked before the file is written, so an exact duplicate costs
    # nothing but the read.
    sample = extract_mod.sample_text(data, file.filename or "")
    duplicate = search.check_duplicate(db, content_hash, text=sample, category=category)

    if duplicate.is_exact:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "This exact file is already in the library"
                    + (
                        f" as '{duplicate.exact_match.original_filename}'."
                        if duplicate.exact_match
                        else "."
                    )
                ),
                "duplicate": duplicate.model_dump(mode="json"),
            },
        )

    document_id = uuid.uuid4()
    stored_path = storage.save_upload(data, file.filename or "", document_id)

    parsed_keywords = [k.strip() for k in keywords.split(",") if k.strip()]

    document = Document(
        id=document_id,
        original_filename=file.filename or str(document_id),
        file_path=str(stored_path),
        file_type=_file_type_of(file.filename or ""),
        category=category,
        title=title.strip(),
        file_hash=content_hash,
        doc_type=doc_type.strip(),
        client=client.strip(),
        sector=sector.strip(),
        service_line=service_line.strip(),
        geography=geography.strip(),
        keywords=parsed_keywords,
        auto_tagged_fields=[],
        training_status=DocumentTrainingStatus.QUEUED,
    )

    db.add(document)
    try:
        db.commit()
    except Exception:
        # Lost a race on the unique hash between the check above and this insert.
        db.rollback()
        storage.delete_document_files(str(stored_path), document_id)
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This exact file is already in the library."
        ) from None

    db.refresh(document)

    return UploadResponse(
        document=DocumentOut.model_validate(document),
        duplicate_warning=duplicate if duplicate.near_matches else None,
    )


@router.post("/check-duplicate", response_model=DuplicateCheckResult)
async def check_duplicate(
    file: UploadFile = File(...),
    category: DocumentCategory | None = Form(None),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> DuplicateCheckResult:
    """Dry-run duplicate check (LIB-UI-06) — nothing is stored.

    Lets the UI warn while a file is still sitting in the drop zone.
    """
    data = await file.read()
    try:
        storage.validate_upload(file.filename or "", file.content_type or "", len(data))
    except storage.UploadRejected as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    sample = extract_mod.sample_text(data, file.filename or "")
    return search.check_duplicate(
        db, storage.hash_bytes(data), text=sample, category=category
    )


# ---------------------------------------------------------------------------
# Train (LIB-UI-04, LIB-IDX-07)
# ---------------------------------------------------------------------------

@router.post("/train", response_model=TrainResponse)
def train(
    payload: TrainRequest,
    force: bool = Query(False, description="Re-index documents already indexed."),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> TrainResponse:
    """Queue indexing for the named documents, or for everything still pending.

    Already-indexed documents are skipped unless `force` is set — that skip is
    LIB-IDX-07 in practice: training after adding one asset processes only the
    new one and leaves the existing library untouched.
    """
    if payload.document_ids:
        documents = list(
            db.execute(
                select(Document).where(Document.id.in_(payload.document_ids))
            ).scalars()
        )
        found = {d.id for d in documents}
        missing = [i for i in payload.document_ids if i not in found]
        if missing:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Unknown document id(s): {', '.join(str(m) for m in missing)}",
            )
    else:
        documents = list(
            db.execute(
                select(Document).where(Document.training_status == DocumentTrainingStatus.QUEUED)
            ).scalars()
        )

    jobs: list[JobOut] = []
    skipped: list[uuid.UUID] = []

    for document in documents:
        if document.training_status == DocumentTrainingStatus.INDEXED and not force:
            skipped.append(document.id)
            continue
        if document.training_status in _IN_FLIGHT:
            # Already running; queueing a second job would race the first over
            # the same chunk rows.
            skipped.append(document.id)
            continue

        job = IndexJob(document_id=document.id, stage=JobStage.queued, progress=0,
                       message="Queued for indexing")
        db.add(job)
        db.commit()
        db.refresh(job)

        indexing.enqueue(document.id, job.id, use_llm=settings.llm_available)
        jobs.append(JobOut.model_validate(job))

    return TrainResponse(jobs=jobs, skipped=skipped)


@router.post("/documents/{document_id}/retrain", response_model=JobOut)
def retrain(
    document_id: uuid.UUID,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    """Re-index a single document (LIB-IDX-07).

    Its own chunks are replaced; no other document is touched.
    """
    document = _get_document(db, document_id)
    if document.training_status in _IN_FLIGHT:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document is already being indexed.")

    job = IndexJob(document_id=document.id, stage=JobStage.queued, message="Queued for re-indexing")
    db.add(job)
    db.commit()
    db.refresh(job)

    indexing.enqueue(document.id, job.id, use_llm=settings.llm_available)
    return JobOut.model_validate(job)


# ---------------------------------------------------------------------------
# Listing and detail
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    category: DocumentCategory | None = None,
    doc_status: DocumentTrainingStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    stmt = select(Document).order_by(Document.created_at.desc())
    if category is not None:
        stmt = stmt.where(Document.category == category)
    if doc_status is not None:
        stmt = stmt.where(Document.training_status == doc_status)

    rows = db.execute(stmt.limit(limit).offset(offset)).scalars()
    return [DocumentOut.model_validate(r) for r in rows]


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def get_document(
    document_id: uuid.UUID,
    include_chunks: bool = Query(False),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> DocumentDetailOut:
    if include_chunks:
        document = db.execute(
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.chunks))
        ).scalars().first()
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        detail = DocumentDetailOut.model_validate(document)
        detail.chunks.sort(key=lambda c: c.chunk_index)
        return detail

    document = _get_document(db, document_id)
    detail = DocumentDetailOut.model_validate(document)
    detail.chunks = []
    return detail


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # The `-> None` annotation below would otherwise be inferred as a response
    # model, which FastAPI rejects for 204 — a 204 must have no body.
    response_model=None,
)
def delete_document(
    document_id: uuid.UUID,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> None:
    document = _get_document(db, document_id)
    stored_path, doc_id = document.file_path, document.id

    # Chunks and jobs go with it via ON DELETE CASCADE.
    db.delete(document)
    db.commit()

    storage.delete_document_files(stored_path, doc_id)


@router.get("/stats")
def stats(
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Per-category counts for the UI tabs (LIB-UI-01)."""
    rows = db.execute(
        select(
            Document.category,
            Document.training_status,
            func.count(Document.id),
        ).group_by(Document.category, Document.training_status)
    ).all()

    by_category: dict[str, dict[str, int]] = {
        c.value: {s.value: 0 for s in DocumentTrainingStatus} | {"total": 0}
        for c in DocumentCategory
    }
    for category, doc_status, count in rows:
        by_category[category.value][doc_status.value] = count
        by_category[category.value]["total"] += count

    chunk_total = db.execute(select(func.count(Chunk.id))).scalar() or 0

    return {
        "categories": by_category,
        "chunk_count": chunk_total,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dim": settings.EMBEDDING_DIM,
        "llm_available": settings.llm_available,
    }


# ---------------------------------------------------------------------------
# Jobs (LIB-UI-05 polling fallback)
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: uuid.UUID,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobOut:
    """Current job state.

    The WebSocket is the primary channel, but a client that reconnects needs a
    way to read where a run got to, and polling this is that fallback.
    """
    job = db.get(IndexJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobOut.model_validate(job)


@router.get("/documents/{document_id}/jobs", response_model=list[JobOut])
def list_document_jobs(
    document_id: uuid.UUID,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    _get_document(db, document_id)
    rows = db.execute(
        select(IndexJob)
        .where(IndexJob.document_id == document_id)
        .order_by(IndexJob.created_at.desc())
    ).scalars()
    return [JobOut.model_validate(r) for r in rows]


# ---------------------------------------------------------------------------
# Search (the LIB-UI-07 seam for Stage 3 matching)
# ---------------------------------------------------------------------------

@router.get("/search", response_model=SearchResponse)
def search_library(
    q: str = Query(..., min_length=2),
    category: DocumentCategory | None = None,
    limit: int = Query(10, ge=1, le=50),
    min_similarity: float = Query(0.0, ge=0.0, le=1.0),
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Semantic retrieval over the indexed library.

    This is what Stage 3 requirement matching will call. Results come straight
    from PostgreSQL with no cache, so a document indexed a second ago is already
    retrievable here — that is LIB-UI-07, no restart required.
    """
    hits = search.search(db, q, category=category, limit=limit, min_similarity=min_similarity)
    return SearchResponse(query=q, hits=hits)


# ---------------------------------------------------------------------------
# Extracted images (LIB-IDX-02)
# ---------------------------------------------------------------------------

@router.get("/documents/{document_id}/images/{image_name}")
def get_image(
    document_id: uuid.UUID,
    image_name: str,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve one extracted image by name."""
    _get_document(db, document_id)

    # Reject any path syntax outright rather than trying to sanitise it — the
    # only legitimate value here is a bare filename.
    if "/" in image_name or "\\" in image_name or image_name.startswith("."):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid image name")

    path = storage.images_dir(document_id) / image_name
    resolved = path.resolve()
    if not resolved.is_relative_to(storage.images_dir(document_id).resolve()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid image name")
    if not resolved.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

    return FileResponse(resolved)


@router.post("/ask", response_model=AnswerOut)
def ask_library(
    payload: AskRequest,
    user: Principal = Depends(current_user),
    db: Session = Depends(get_db),
) -> AnswerOut:
    """Answer a question from the library, with citations.

    Retrieval-augmented generation over the same index `/search` reads: the
    question is embedded, the nearest chunks are pulled, and only those chunks
    are put in front of the model. Nothing is answered from the model's own
    knowledge — an answer the library cannot support comes back as a refusal
    with `grounded: false`.

    Note this is not a Section 6 deliverable. Section 6 owns retrieval; Stage 3
    requirement matching owns generation and will call `/search` directly. This
    endpoint exists so the library can be demonstrated end to end today, and it
    adds no state — remove it and indexing and search are unaffected.
    """
    return rag.answer(
        db,
        payload.question,
        category=payload.category,
        limit=payload.limit,
    )


@router.get("/stages")
def stages(user: Principal = Depends(current_user)) -> dict:
    """The LIB-UI-05 stage labels, so the UI does not hardcode them."""
    return {"stages": [{"value": s.value, "label": STAGE_LABELS[s]} for s in JobStage]}
