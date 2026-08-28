"""The indexing pipeline (LIB-UI-04, LIB-UI-05, LIB-IDX-05, LIB-IDX-07).

One task per document. That is what makes indexing incremental (LIB-IDX-07):
adding an asset touches only its own rows, and nothing in this file reads or
rewrites another document's chunks. Re-training one document deletes its own
chunks and rebuilds them — the rest of the library is never re-embedded.

Stage names published here are fixed by LIB-UI-05:
    Parsing -> Tagging -> Generating Embeddings -> Indexing Complete

Note on the Celery task names below: they are registered as
`app.tasks.indexing.index_document` / `...reindex_document`, which no longer
matches this module's dotted path. That is deliberate and must not be "fixed" —
the name is the routing key a queued message carries, so renaming it would
orphan any task already sitting in Redis, and the worker resolves tasks by
registered name rather than by module. `app/tasks/indexing.py` in this tree is a
tombstone from the earlier flat layout; this module is the live one.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import delete, select

from app.celery_app import celery_app  # noqa: F401  (ensures the app is configured)
from app.core.database import SessionLocal
from app.models import Chunk, Document, DocumentImage, IndexJob
from app.models.enums import DocumentTrainingStatus, JOB_STAGE_TO_DOCUMENT_STATUS as STAGE_TO_STATUS, JobStage
from app.services.library import chunking, embeddings, metadata
from app.services.library import library_progress as progress
from app.services.library.parsers import registry
from app.services.library.parsers.extract import ExtractionError, extract

logger = logging.getLogger(__name__)

# Embeddings are generated in batches so a 400-chunk methodology document
# reports progress as it goes instead of sitting silent on one call.
EMBED_BATCH_SIZE = 32

# Progress is reported as a percentage of the whole job. Parsing and tagging get
# a fixed share; embedding — the slow part — gets the rest.
PROGRESS_PARSING = 10
PROGRESS_PARSED = 30
PROGRESS_TAGGED = 45
PROGRESS_EMBED_START = 45
PROGRESS_EMBED_END = 95


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _advance(
    db,
    job: IndexJob,
    stage: JobStage,
    percent: int,
    message: str = "",
    document: Document | None = None,
) -> None:
    """Persist job state and publish it.

    Both, not either: the WebSocket carries live updates, but a client that
    connects late or reloads mid-run reads the persisted row instead of missing
    the stage entirely.

    Passing `document` also mirrors the stage onto its 1.1.2 `training_status`
    column, which is what a reader outside Section 6 looks at — they have no
    reason to know `index_jobs` exists. Routed through STAGE_TO_STATUS so the
    two can never disagree.
    """
    job.stage = stage
    job.progress = max(0, min(100, percent))
    job.message = message
    if document is not None:
        document.training_status = STAGE_TO_STATUS[stage]
    db.commit()
    progress.publish(job.id, job.document_id, stage, job.progress, message)


@celery_app.task(bind=True, name="app.tasks.indexing.index_document", max_retries=0)
def index_document(self, document_id: str, job_id: str, use_llm: bool = True) -> dict:
    """Parse, tag, embed and index one document.

    `max_retries=0` is deliberate: a parse failure is almost always a bad file,
    and a silent Celery retry would re-run OCR on it three times and confuse the
    progress display. Failures are recorded on the document for the user to see
    and re-trigger explicitly.
    """
    db = SessionLocal()
    doc_uuid = uuid.UUID(document_id)
    job_uuid = uuid.UUID(job_id)

    try:
        document = db.get(Document, doc_uuid)
        job = db.get(IndexJob, job_uuid)

        if document is None or job is None:
            # Deleted between enqueue and execution. Not an error worth retrying.
            logger.warning("Document %s or job %s no longer exists", document_id, job_id)
            return {"status": "missing", "document_id": document_id}

        document.training_status = DocumentTrainingStatus.PARSING
        document.training_error = ""
        db.commit()

        try:
            result = _run_pipeline(db, document, job, use_llm=use_llm)
        except Exception as exc:
            logger.exception("Indexing failed for document %s", document_id)
            _fail(db, document, job, str(exc))
            return {"status": "failed", "document_id": document_id, "error": str(exc)}

        return result

    finally:
        db.close()


def _fail(db, document: Document, job: IndexJob, message: str) -> None:
    # Truncated so a stack-trace-shaped message cannot bloat the row or the UI.
    document.training_status = DocumentTrainingStatus.FAILED
    document.training_error = message[:2000]
    db.commit()
    _advance(db, job, JobStage.FAILED, job.progress, message[:500])


def _run_pipeline(db, document: Document, job: IndexJob, use_llm: bool) -> dict:
    # ---- Parsing -----------------------------------------------------------
    _advance(
        db,
        job,
        JobStage.PARSING,
        PROGRESS_PARSING,
        f"Reading {document.original_filename}",
        document,
    )

    try:
        raw = extract(document.file_path, document.original_filename, document.id)
    except ExtractionError as exc:
        raise RuntimeError(f"Could not read the file: {exc}") from exc

    parse_result = registry.parse(document.category, raw, use_llm=use_llm)

    if not parse_result.sections:
        raise RuntimeError(
            "No text could be extracted from this file, so there is nothing to index. "
            "If it is a scanned document, check that it is legible."
        )

    document.page_count = raw.page_count
    _record_images(db, document, raw)
    db.commit()

    section_summary = ", ".join(parse_result.section_names[:8]) or "1 section"
    _advance(
        db,
        job,
        JobStage.PARSING,
        PROGRESS_PARSED,
        f"Parsed {raw.page_count} page(s): {section_summary}",
    )

    # ---- Tagging (LIB-IDX-06) ---------------------------------------------
    _advance(db, job, JobStage.TAGGING, PROGRESS_PARSED, "Extracting metadata", document)

    # Whatever the uploader typed is already on the row and must survive; the
    # parser's own findings (a case study's Client line, a certificate's type)
    # rank above the generic heuristics but below the user.
    user_supplied = {
        "doc_type": document.doc_type,
        "client": document.client,
        "sector": document.sector,
        "service_line": document.service_line,
        "geography": document.geography,
        "keywords": document.keywords or [],
    }

    # Captured before the parser's values are merged in, so "typed by a human"
    # stays distinguishable from "found by a machine".
    user_typed = {key for key, value in user_supplied.items() if value}

    for key, value in parse_result.doc_metadata.items():
        if key in user_supplied and not user_supplied[key] and isinstance(value, str) and value:
            user_supplied[key] = value

    parser_derived = {key for key in user_supplied if key not in user_typed and user_supplied[key]}

    extracted = metadata.extract(
        raw.text,
        document.original_filename,
        document.category.value,
        user_supplied=user_supplied,
        use_llm=use_llm,
    )

    document.doc_type = extracted.doc_type[:128]
    document.client = extracted.client[:255]
    document.sector = extracted.sector[:255]
    document.service_line = extracted.service_line[:255]
    document.geography = extracted.geography[:255]
    document.keywords = extracted.keywords

    # metadata.extract() treats the parser's findings as user-supplied and so
    # will not flag them; they were not typed by a human either, so they belong
    # in the auto-tagged set for LIB-UI-03.
    document.auto_tagged_fields = sorted(set(extracted.auto_tagged_fields) | parser_derived)

    if not document.title:
        document.title = _derive_title(raw, parse_result, document.original_filename)

    db.commit()

    _advance(
        db,
        job,
        JobStage.TAGGING,
        PROGRESS_TAGGED,
        f"Tagged as {document.doc_type or 'untyped'}"
        + (f" · {document.client}" if document.client else ""),
    )

    # ---- Chunking + embedding (LIB-IDX-05) --------------------------------
    chunks = chunking.chunk_sections(parse_result.sections)
    if not chunks:
        raise RuntimeError("Parsing produced sections but no chunks; the file may be empty.")

    _advance(
        db,
        job,
        JobStage.EMBEDDING,
        PROGRESS_EMBED_START,
        f"Generating embeddings for {len(chunks)} chunk(s)",
        document,
    )

    # Re-indexing: drop this document's own chunks and no others (LIB-IDX-07).
    # Done here rather than at the start so a failed parse leaves the previously
    # indexed version intact.
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    db.commit()

    provider = embeddings.get_provider()
    span = PROGRESS_EMBED_END - PROGRESS_EMBED_START
    written = 0

    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        vectors = provider.embed_documents([c.content for c in batch])

        if len(vectors) != len(batch):
            raise RuntimeError(
                f"Embedding provider returned {len(vectors)} vectors for {len(batch)} chunks."
            )

        for offset, (chunk, vector) in enumerate(zip(batch, vectors)):
            db.add(
                Chunk(
                    document_id=document.id,
                    chunk_index=start + offset,
                    content=chunk.content,
                    embedding=vector,
                    category=document.category,
                    section_name=chunk.section_name[:255],
                    phase=chunk.phase[:255],
                    page_number=chunk.page_number,
                    token_count=chunk.token_count,
                    image_paths=chunk.image_paths,
                )
            )

        db.commit()
        written += len(batch)
        percent = PROGRESS_EMBED_START + int(span * written / len(chunks))
        _advance(
            db,
            job,
            JobStage.EMBEDDING,
            percent,
            f"Embedded {written} of {len(chunks)} chunks",
        )

    # ---- Done -------------------------------------------------------------
    document.chunk_count = written
    document.training_status = DocumentTrainingStatus.INDEXED
    document.indexed_at = _utcnow()
    document.training_error = "; ".join(parse_result.warnings)[:2000] if parse_result.warnings else ""
    db.commit()

    # Committing is the whole of LIB-UI-07: search reads PostgreSQL directly with
    # no cache, so these rows are live to Stage 3 matching from this moment on.
    # No reload, no restart, no invalidation step.
    _advance(
        db,
        job,
        JobStage.COMPLETE,
        100,
        f"Indexed {written} chunk(s) across {raw.page_count} page(s)",
        document,
    )

    return {
        "status": "indexed",
        "document_id": str(document.id),
        "chunks": written,
        "pages": raw.page_count,
        "images": len(raw.image_paths),
        "used_llm": parse_result.used_llm,
        "warnings": parse_result.warnings,
    }


def _record_images(db, document: Document, raw) -> None:
    """Index the extracted images into 1.1.2's `document_images` (LIB-IDX-02).

    The chunk-level `image_paths` list is what search returns alongside a hit,
    but it only covers pages that produced a chunk. `document_images` is the
    document-wide inventory, and it is the table a reader outside Section 6
    looks at — a Stage 3 proposal builder wants every figure in a case study,
    not just the ones near matching text.

    Cleared and rewritten rather than appended to, because re-training re-runs
    extraction and would otherwise double every row (LIB-IDX-07).
    """
    db.execute(delete(DocumentImage).where(DocumentImage.document_id == document.id))

    for page in raw.pages:
        for path in page.image_paths:
            db.add(
                DocumentImage(
                    document_id=document.id,
                    file_path=path,
                    page_number=page.number,
                    # No caption yet: nothing in the pipeline reads figure text.
                    # Nullable in 1.1.2, so leaving it unset is a valid row.
                    caption=None,
                )
            )


def _derive_title(raw, parse_result, filename: str) -> str:
    """Best-effort human title: the document's own first heading, else its name."""
    for page in raw.pages:
        for line in page.text.split("\n"):
            candidate = line.strip().lstrip("#").strip()
            if 8 <= len(candidate) <= 160:
                return candidate[:512]
    from pathlib import Path

    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()[:512]


@celery_app.task(name="app.tasks.indexing.reindex_document")
def reindex_document(document_id: str, use_llm: bool = True) -> dict:
    """Re-run indexing for one already-uploaded document (LIB-IDX-07).

    Creates its own job row so the UI can follow it exactly like a first Train.
    """
    db = SessionLocal()
    try:
        document = db.get(Document, uuid.UUID(document_id))
        if document is None:
            return {"status": "missing", "document_id": document_id}

        job = IndexJob(document_id=document.id, stage=JobStage.QUEUED)
        db.add(job)
        db.commit()
        job_id = str(job.id)
    finally:
        db.close()

    return index_document(document_id, job_id, use_llm)


def enqueue(document_id: uuid.UUID | str, job_id: uuid.UUID | str, use_llm: bool = True):
    """Queue an indexing run. Called by the API's Train endpoint."""
    return index_document.delay(str(document_id), str(job_id), use_llm)


def pending_document_ids(db) -> list[uuid.UUID]:
    """Documents uploaded but not yet trained — what Train-all operates on."""
    rows = db.execute(
        select(Document.id).where(Document.training_status == DocumentTrainingStatus.QUEUED)
    ).scalars()
    return list(rows)
