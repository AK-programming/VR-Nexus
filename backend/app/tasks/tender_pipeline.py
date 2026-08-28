"""
Tender analysis pipeline (Celery) — Stages 2→4, TRK-03.

The upload endpoint (routes/tenders.py) now only validates, saves, and creates
the Tender(UPLOADED) row, then enqueues this task. Everything heavy runs here,
in the worker, exactly like the Evidence Library's index_document task — the
worker already has the embedding model and shared storage mounted, and
services/progress.py is deliberately FastAPI-free so the same publish_progress()
calls the old in-request version used work unchanged from a worker.

Stage map (status -> percent), mirroring services/progress.PIPELINE_STAGES:

    PARSING             5   extract text/tables per page (+ best-effort metadata)
    CHUNKING          20-33 section-aware chunking; persist TenderChunk rows
    EXTRACTING        35-60 run_extraction() — owns its own progress + hash dedup
    MERGING           62    dedup already happened in extraction; nominal milestone
    MATCHING          65-82 match each requirement to the Evidence Library
    REPORTING         85-90 marks available/captured totals
    ASSEMBLING_FOLDER 92-98 build the output folder + zip
    READY_FOR_REVIEW  100   pause for human review (NOT socket-terminal)

A run that raises anywhere sets status FAILED and publishes it (terminal for the
progress socket). max_retries=0 for the same reason as indexing: a failure here
is almost always a bad file or a missing API key, and silently re-running a
long OCR + LLM extraction three times would only confuse the progress display
and burn API budget. Every stage is idempotent (it clears its own prior rows
first) so an explicit re-run is safe.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import delete

from app.celery_app import celery_app  # noqa: F401  (ensures the app is configured)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.enums import MatchReviewStatus, MatchType, TenderStatus
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.services.chunking import (
    chunk_sectioned_pages,
    detect_section_boundaries,
    guard_against_whole_document_ingestion,
)
from app.services.extraction import extract_tender_metadata, run_extraction
from app.services.library.search import search
from app.services.pdf_extraction import extract_pdf_pages
from app.services.progress import publish_progress

logger = logging.getLogger(__name__)

# Match thresholds, taken verbatim from the MatchType enum's own definitions in
# app/models/enums.py so the two can never drift:
#   AUTO       confidence >= 0.85
#   SUGGESTED  0.50 - 0.84
#   MISSING    < 0.50
AUTO_MATCH_THRESHOLD = 0.85
SUGGESTED_MATCH_FLOOR = 0.50
MATCH_TOP_K = 5  # candidate evidence documents considered per requirement

# Opening pages sampled for the one-shot tender-metadata extraction.
METADATA_SAMPLE_PAGES = 5


# --------------------------------------------------------------------------- #
# progress helper                                                             #
# --------------------------------------------------------------------------- #
def _advance(
    db,
    tender: Tender,
    status: TenderStatus,
    percent: int,
    message: str = "",
    *,
    count: int | None = None,
) -> None:
    """Persist stage state onto the Tender row AND publish it.

    Both, not either: the WebSocket carries live frames, but a client that
    connects late or reloads mid-run reads the persisted row (TRK-04) instead
    of missing the stage. Mirrors tasks/library_indexing._advance.
    """
    tender.status = status
    tender.progress_percent = max(0, min(100, percent))
    tender.progress_message = (message or "")[:500] or None
    if count is not None:
        tender.extracted_requirements_count = count
    db.commit()
    publish_progress(
        str(tender.id),
        status,
        percent=tender.progress_percent,
        message=message or None,
        extracted_requirements_count=tender.extracted_requirements_count,
    )


# --------------------------------------------------------------------------- #
# task entrypoint                                                             #
# --------------------------------------------------------------------------- #
@celery_app.task(
    bind=True,
    name="app.tasks.tender_pipeline.run_tender_pipeline",
    max_retries=0,
    # Extraction makes many sequential Claude calls; a large tender can outlast
    # the app-wide 1800s soft limit. Override it here rather than globally, so
    # only this task gets the longer leash.
    soft_time_limit=3600,
    time_limit=3900,
)
def run_tender_pipeline(self, tender_id: str) -> dict:
    """Parse → chunk → extract → merge → match → report → assemble one tender."""
    db = SessionLocal()
    try:
        tender = db.get(Tender, uuid.UUID(tender_id))
        if tender is None:
            # Deleted between enqueue and execution. Not an error worth retrying.
            logger.warning("Tender %s no longer exists; nothing to process.", tender_id)
            return {"status": "missing", "tender_id": tender_id}

        try:
            return _run_pipeline(db, tender)
        except Exception as exc:  # noqa: BLE001 - record failure state either way
            logger.exception("Tender pipeline failed for %s", tender_id)
            _fail(db, tender, str(exc))
            return {"status": "failed", "tender_id": tender_id, "error": str(exc)}
    finally:
        db.close()


def _fail(db, tender: Tender, message: str) -> None:
    # The failing stage may have left uncommitted work; discard it, then record
    # the failure. Prior stages are already committed by _advance and survive.
    db.rollback()
    tender.status = TenderStatus.FAILED
    tender.progress_message = message[:500]
    db.commit()
    publish_progress(str(tender.id), TenderStatus.FAILED, message=message[:500])


# --------------------------------------------------------------------------- #
# pipeline                                                                    #
# --------------------------------------------------------------------------- #
def _run_pipeline(db, tender: Tender) -> dict:
    content = _read_source(tender)

    # ---- PARSING ----------------------------------------------------------
    _advance(db, tender, TenderStatus.PARSING, 5, "Extracting text and tables per page.")
    pages = extract_pdf_pages(content)
    if not pages:
        raise RuntimeError("No pages could be extracted from this PDF.")
    tender.page_count = len(pages)
    db.commit()

    _extract_and_apply_metadata(db, tender, pages)

    # ---- CHUNKING ---------------------------------------------------------
    _advance(
        db, tender, TenderStatus.CHUNKING, 20,
        f"Detecting sections across {len(pages)} page(s).",
    )
    sectioned = detect_section_boundaries(pages)
    chunks = chunk_sectioned_pages(sectioned)
    guard_against_whole_document_ingestion(chunks)

    # Idempotent re-run: replace this tender's own chunks, nothing else.
    db.execute(delete(TenderChunk).where(TenderChunk.tender_id == tender.id))
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
    _advance(
        db, tender, TenderStatus.CHUNKING, 33,
        f"Chunked into {len(chunks)} chunk(s) across "
        f"{len({c.section for c in chunks})} section(s).",
    )

    # ---- EXTRACTING (35-60%) + MERGING -----------------------------------
    # run_extraction dedups by clause+description hash as it goes, so MERGING is
    # effectively already done when it returns; we mark it for the timeline.
    db.execute(delete(Requirement).where(Requirement.tender_id == tender.id))
    db.commit()
    extraction_result = asyncio.run(run_extraction(db, tender))
    created = extraction_result["created"]
    _advance(
        db, tender, TenderStatus.MERGING, 62,
        f"Merged & de-duplicated: {created} unique requirement(s).",
        count=created,
    )

    # ---- MATCHING (65-82%) ------------------------------------------------
    match_summary = _run_matching(db, tender)

    # ---- REPORTING (85-90%) ----------------------------------------------
    _advance(db, tender, TenderStatus.REPORTING, 85, "Computing marks and coverage.")
    report_summary = _compute_report(db, tender)
    _advance(
        db, tender, TenderStatus.REPORTING, 90,
        f"Report ready: {report_summary['captured']:g}/{report_summary['available']:g} "
        "marks auto-covered.",
    )

    # ---- ASSEMBLING_FOLDER (92-98%) --------------------------------------
    _advance(db, tender, TenderStatus.ASSEMBLING_FOLDER, 92, "Assembling output folder.")
    _assemble_folder(db, tender)
    _advance(db, tender, TenderStatus.ASSEMBLING_FOLDER, 98, "Output folder assembled.")

    # ---- READY_FOR_REVIEW (100%) -----------------------------------------
    # Deliberately NOT terminal for the socket: the run has paused for a human,
    # and the frontend treats READY_FOR_REVIEW as "settled, awaiting review".
    _advance(
        db, tender, TenderStatus.READY_FOR_REVIEW, 100,
        "Analysis complete — ready for review.",
        count=created,
    )

    return {
        "status": "ready_for_review",
        "tender_id": str(tender.id),
        "requirements": created,
        "failed_chunks": extraction_result["failed_chunks"],
        **match_summary,
        **report_summary,
    }


def _read_source(tender: Tender) -> bytes:
    path = Path(tender.file_path)
    if not path.is_file():
        raise RuntimeError(
            f"Source PDF is missing at {tender.file_path!r}; cannot process this tender."
        )
    return path.read_bytes()


# --------------------------------------------------------------------------- #
# metadata (best-effort)                                                      #
# --------------------------------------------------------------------------- #
def _extract_and_apply_metadata(db, tender: Tender, pages) -> None:
    """One-shot tender-metadata extraction over the opening pages. Never fatal:
    any failure leaves the columns null for the user to fill in via PATCH."""
    sample = "\n\n".join(p.text for p in pages[:METADATA_SAMPLE_PAGES] if p.text)
    meta = asyncio.run(extract_tender_metadata(sample))
    if not meta:
        return

    for column in ("reference_id", "issuing_authority", "sector", "location"):
        value = _clean(meta.get(column))
        if value:
            setattr(tender, column, value)

    value = _parse_money(meta.get("tender_value"))
    if value is not None:
        tender.tender_value = value

    deadline = _parse_date(meta.get("submission_deadline"))
    if deadline is not None:
        tender.submission_deadline = deadline

    db.commit()


def _clean(value) -> str | None:
    v = (value or "").strip()
    if not v or v.upper() in ("N/A", "NA", "NONE", "UNKNOWN", "UNNUMBERED"):
        return None
    return v[:500]


def _parse_money(value) -> Decimal | None:
    v = _clean(value)
    if not v:
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", v)
    if not match:
        return None
    try:
        return Decimal(match.group().replace(",", ""))
    except InvalidOperation:
        return None


def _parse_date(value) -> date | None:
    v = _clean(value)
    if not v:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", v)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group())
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# MATCHING                                                                    #
# --------------------------------------------------------------------------- #
def _run_matching(db, tender: Tender) -> dict:
    """For each requirement, semantic-search the Evidence Library and record the
    candidate documents as RequirementEvidenceMatch rows, typed by confidence.

    A requirement whose best candidate clears 0.85 gets one AUTO row per
    qualifying document; 0.50-0.84 gets SUGGESTED rows; if nothing clears 0.50
    we still record the single closest document as MISSING so the gap (and what
    came nearest) is visible. Only an empty library (no candidate at all) leaves
    a requirement with no row — there is no document to point one at.
    """
    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id)
        .order_by(Requirement.evidence_required.desc(), Requirement.created_at)
        .all()
    )

    # Idempotent re-run: clear prior matches for this tender's requirements.
    req_ids = [r.id for r in requirements]
    if req_ids:
        db.execute(
            delete(RequirementEvidenceMatch).where(
                RequirementEvidenceMatch.requirement_id.in_(req_ids)
            )
        )
        db.commit()

    total = len(requirements)
    auto = suggested = missing = no_candidates = 0

    _advance(
        db, tender, TenderStatus.MATCHING, 65,
        f"Matching {total} requirement(s) to the evidence library.",
    )
    if total == 0:
        return {"auto_matches": 0, "suggested_matches": 0, "missing_matches": 0,
                "unmatched_no_library": 0}

    for i, req in enumerate(requirements, start=1):
        query = (req.description or "").strip()
        hits = search(db, query, limit=MATCH_TOP_K) if query else []

        # Several chunks of one document can rank adjacently; collapse to the
        # document's single best score so a requirement gets one row per doc.
        best_by_doc: dict[uuid.UUID, float] = {}
        for h in hits:
            if h.document_id not in best_by_doc or h.similarity > best_by_doc[h.document_id]:
                best_by_doc[h.document_id] = h.similarity
        ranked = sorted(best_by_doc.items(), key=lambda kv: kv[1], reverse=True)

        qualifying = [(doc_id, sim) for doc_id, sim in ranked if sim >= SUGGESTED_MATCH_FLOOR]

        if qualifying:
            for doc_id, sim in qualifying:
                match_type = MatchType.AUTO if sim >= AUTO_MATCH_THRESHOLD else MatchType.SUGGESTED
                if match_type == MatchType.AUTO:
                    auto += 1
                else:
                    suggested += 1
                db.add(
                    RequirementEvidenceMatch(
                        requirement_id=req.id,
                        document_id=doc_id,
                        confidence_score=round(sim, 4),
                        match_type=match_type,
                        review_status=MatchReviewStatus.PENDING,
                    )
                )
        elif ranked:
            # Closest candidate is below the suggested floor: record the gap,
            # pointing at what came nearest.
            doc_id, sim = ranked[0]
            missing += 1
            db.add(
                RequirementEvidenceMatch(
                    requirement_id=req.id,
                    document_id=doc_id,
                    confidence_score=round(sim, 4),
                    match_type=MatchType.MISSING,
                    review_status=MatchReviewStatus.PENDING,
                )
            )
        else:
            # Empty library (or blank requirement): no document to reference.
            no_candidates += 1

        if i % 10 == 0 or i == total:
            percent = 65 + int((i / total) * 17)  # 65 -> 82
            _advance(
                db, tender, TenderStatus.MATCHING, percent,
                f"Matched {i} of {total} requirement(s).",
            )

    return {
        "auto_matches": auto,
        "suggested_matches": suggested,
        "missing_matches": missing,
        "unmatched_no_library": no_candidates,
    }


# --------------------------------------------------------------------------- #
# REPORTING                                                                   #
# --------------------------------------------------------------------------- #
def _compute_report(db, tender: Tender) -> dict:
    """Marks available vs. captured. A requirement counts as captured when it
    has an ACCEPTED match, or an AUTO match that has not been rejected. This is
    the same rule as routes/tenders._requirement_covered, so the pipeline's
    persisted totals and the on-demand /report endpoint always agree — and a
    reviewer rejecting an auto-match correctly drops its marks on the next
    rebuild (finalize)."""
    requirements = db.query(Requirement).filter(Requirement.tender_id == tender.id).all()

    available = Decimal("0")
    captured = Decimal("0")
    for req in requirements:
        if req.marks is None:
            continue
        marks = Decimal(str(req.marks))
        available += marks
        covered = any(
            m.review_status == MatchReviewStatus.ACCEPTED
            or (m.match_type == MatchType.AUTO and m.review_status != MatchReviewStatus.REJECTED)
            for m in req.evidence_matches
        )
        if covered:
            captured += marks

    has_marks = available > 0
    tender.total_marks_available = available if has_marks else None
    tender.total_marks_captured = captured if has_marks else None
    db.commit()
    return {"available": float(available), "captured": float(captured)}


# --------------------------------------------------------------------------- #
# ASSEMBLING_FOLDER                                                           #
# --------------------------------------------------------------------------- #
def _assemble_folder(db, tender: Tender) -> str:
    """Write OUTPUT_STORAGE_DIR/{tender_id}/ with a requirements+matches
    workbook and a summary.json, then zip it to OUTPUT_STORAGE_DIR/{tender_id}.zip.
    Records both paths on the Tender row (TN-OUT-02/03/04)."""
    settings = get_settings()
    out_root = Path(settings.OUTPUT_STORAGE_DIR)
    folder = out_root / str(tender.id)
    folder.mkdir(parents=True, exist_ok=True)

    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id)
        .order_by(Requirement.page_number, Requirement.created_at)
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Requirements"
    ws.append(
        ["#", "Page", "Section", "Clause", "Description", "Mandatory",
         "Evaluation Impact", "Marks", "Evidence Required", "Status"]
    )
    for idx, r in enumerate(requirements, start=1):
        ws.append([
            idx,
            r.page_number if r.page_number is not None else "",
            r.section_name or "",
            r.clause_reference or "",
            (r.description or "")[:32000],  # Excel's per-cell character ceiling
            _yn(r.is_mandatory),
            r.evaluation_impact.value if r.evaluation_impact else "",
            float(r.marks) if r.marks is not None else "",
            "Yes" if r.evidence_required else "No",
            r.status.value,
        ])

    ws2 = wb.create_sheet("Evidence Matches")
    ws2.append(
        ["Requirement Clause", "Requirement (excerpt)", "Matched Document",
         "Similarity", "Match Type", "Review Status"]
    )
    matches = (
        db.query(RequirementEvidenceMatch)
        .join(Requirement, RequirementEvidenceMatch.requirement_id == Requirement.id)
        .filter(Requirement.tender_id == tender.id)
        .all()
    )
    for m in matches:
        doc = m.document
        ws2.append([
            m.requirement.clause_reference or "",
            (m.requirement.description or "")[:200],
            (doc.title or doc.original_filename) if doc else "",
            float(m.confidence_score) if m.confidence_score is not None else "",
            m.match_type.value,
            m.review_status.value,
        ])

    wb.save(str(folder / "requirements_and_matches.xlsx"))

    summary = {
        "tender": {
            "id": str(tender.id),
            "name": tender.name,
            "original_filename": tender.original_filename,
            "reference_id": tender.reference_id,
            "issuing_authority": tender.issuing_authority,
            "sector": tender.sector,
            "location": tender.location,
            "tender_value": float(tender.tender_value) if tender.tender_value is not None else None,
            "submission_deadline": (
                tender.submission_deadline.isoformat() if tender.submission_deadline else None
            ),
            "page_count": tender.page_count,
        },
        "requirements_total": len(requirements),
        "evidence_matches_total": len(matches),
        "marks_available": (
            float(tender.total_marks_available) if tender.total_marks_available is not None else None
        ),
        "marks_captured": (
            float(tender.total_marks_captured) if tender.total_marks_captured is not None else None
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    zip_path = out_root / f"{tender.id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(folder.rglob("*")):
            if file.is_file():
                zf.write(file, arcname=file.relative_to(folder))

    tender.output_folder_path = str(folder)
    tender.output_zip_path = str(zip_path)
    db.commit()
    return str(zip_path)


def _yn(value) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return ""


# --------------------------------------------------------------------------- #
# rebuild (finalize)                                                          #
# --------------------------------------------------------------------------- #
def rebuild_outputs(db, tender: Tender) -> str:
    """Recompute the marks report and reassemble the output folder/zip from the
    tender's CURRENT match state.

    Called by POST /api/tenders/{id}/finalize after a human has accepted /
    rejected / reassigned matches, so the persisted marks and the downloadable
    output reflect the reviewed result rather than the pipeline's first-pass
    auto-matches. Returns the zip path.
    """
    _compute_report(db, tender)
    return _assemble_folder(db, tender)


# --------------------------------------------------------------------------- #
# enqueue                                                                     #
# --------------------------------------------------------------------------- #
def enqueue(tender_id: uuid.UUID | str):
    """Queue a pipeline run. Called by the API's upload endpoint."""
    return run_tender_pipeline.delay(str(tender_id))
