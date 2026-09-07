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
import shutil
import traceback
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import delete, select, update

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
from app.services.extraction import TenderCancelled, extract_tender_metadata, run_extraction
from app.services.library.search import search
from app.services.pdf_extraction import extract_pdf_pages
from app.services.progress import publish_progress

logger = logging.getLogger(__name__)

# Match thresholds, taken verbatim from the MatchType enum's own definitions in
# app/models/enums.py so the two can never drift:
#   AUTO       confidence >= 0.85
#   SUGGESTED  0.60 - 0.84
#   MISSING    < 0.60
#
# SUGGESTED_MATCH_FLOOR was 0.50 and MATCH_TOP_K was 5. Raised the floor and
# halved top_k because every qualifying candidate becomes its own PENDING row a
# person has to click through, and at the old settings a single requirement
# could hand back up to 5 near-duplicate suggestions clustered a few points
# apart — reviewers were working through hundreds of rows, most of them low-
# value. Fewer, better candidates below; AUTO rows below the review queue
# entirely (see the review_status change in _run_matching).
AUTO_MATCH_THRESHOLD = 0.85
SUGGESTED_MATCH_FLOOR = 0.60
MATCH_TOP_K = 2  # candidate evidence documents considered per requirement

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
    expected_generation: int,
) -> None:
    """Persist stage state onto the Tender row AND publish it - but only if
    this run is still the one that owns the row.

    `expected_generation` is the tender's run_generation at the moment this
    task started (captured once in run_tender_pipeline and threaded down
    through every call in this module). Cancel and reprocess both bump the
    column the instant a person acts, so the UPDATE below is conditioned on
    the generation still matching, in the UPDATE's own WHERE clause rather
    than a separate SELECT-then-write: there is no window between checking
    and writing for another process to slip through. A worker that is
    mid-stage when someone clicks Stop - or Stop, then Retry, before this
    worker noticed - finds its next write rejected outright (raises
    TenderCancelled, same as the cooperative check in services/extraction.py)
    instead of silently overwriting whatever the person's action, or a
    second worker's fresh run, just set.

    Both DB row and pub/sub, not either: the WebSocket carries live frames,
    but a client that connects late or reloads mid-run reads the persisted
    row (TRK-04) instead of missing the stage. Mirrors
    tasks/library_indexing._advance.
    """
    values: dict = {
        "status": status,
        "progress_percent": max(0, min(100, percent)),
        "progress_message": (message or "")[:500] or None,
    }
    if count is not None:
        values["extracted_requirements_count"] = count

    result = db.execute(
        update(Tender)
        .where(Tender.id == tender.id, Tender.run_generation == expected_generation)
        .values(**values)
    )
    db.commit()

    if result.rowcount == 0:
        raise TenderCancelled()

    db.refresh(tender)
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
def run_tender_pipeline(self, tender_id: str, expected_generation: int) -> dict:
    """Parse → chunk → extract → merge → match → report → assemble one tender.

    `expected_generation` is the tender's run_generation at the moment this
    task was enqueued (see enqueue() below) - it is what every write this
    task makes is conditioned on, all the way down through _advance/_fail.
    Passed explicitly rather than re-read from the row at task start: a task
    can sit queued for a while, and by the time it actually runs a later
    Reprocess may have bumped the column again, enqueueing a second task at
    that newer generation. Re-reading here would make this task believe it
    owns that same newer generation too - two tasks racing as if they were
    one. Carrying the value the caller actually had in hand at enqueue time
    keeps each task tied to the one specific attempt it represents.
    """
    db = SessionLocal()
    try:
        tender = db.get(Tender, uuid.UUID(tender_id))
        if tender is None:
            # Deleted between enqueue and execution. Not an error worth retrying.
            logger.warning("Tender %s no longer exists; nothing to process.", tender_id)
            return {"status": "missing", "tender_id": tender_id}

        if tender.run_generation != expected_generation:
            # Superseded before this task even got a worker slot - e.g. it sat
            # queued behind other jobs while a Stop, then Retry, already moved
            # the tender on. Nothing to do; the newer task owns the row now.
            logger.info(
                "Tender %s superseded before its pipeline started "
                "(expected generation %s, row is now at %s); skipping.",
                tender_id, expected_generation, tender.run_generation,
            )
            return {"status": "superseded", "tender_id": tender_id}

        # Claim this task instance on the row so Cancel can revoke it directly,
        # on top of the cooperative checks the generation guard provides below.
        tender.celery_task_id = self.request.id
        db.commit()

        try:
            return _run_pipeline(db, tender, expected_generation)
        except TenderCancelled:
            logger.info("Tender %s stopped by user.", tender_id)
            _fail(db, tender, "Stopped by user.", expected_generation)
            return {"status": "cancelled", "tender_id": tender_id}
        except Exception as exc:  # noqa: BLE001 - record failure state either way
            logger.exception("Tender pipeline failed for %s", tender_id)
            _fail(db, tender, str(exc) or type(exc).__name__, expected_generation, exc=exc)
            return {"status": "failed", "tender_id": tender_id, "error": str(exc)}
    finally:
        db.close()


#: How much of the exception detail is kept on the row. Enough for the class,
#: the message and the last few traceback frames — the part that says which call
#: failed — without letting a pathological stack fill the column.
ERROR_DETAIL_LIMIT = 4000

#: Frames kept from the tail of the traceback. The tail is where the failure is;
#: the head is this module's own dispatch, which the reader already knows.
ERROR_FRAME_COUNT = 6


def _error_detail(exc: BaseException) -> str:
    """The exception rendered for a human reading the error log.

    Class name first — a bare `str(exc)` is empty for plenty of exceptions
    (`RuntimeError()`, `KeyError` renders only the key), and "something failed"
    with no type is the least useful line an error log can hold. The last few
    frames follow, newest last, because "which call raised" is the question a
    failure actually has to answer.
    """
    head = f"{type(exc).__name__}: {exc}".strip().rstrip(":").strip()
    frames = traceback.format_exception(type(exc), exc, exc.__traceback__)[1:]
    tail = "".join(frames[-ERROR_FRAME_COUNT:]).strip()
    detail = f"{head}\n\n{tail}" if tail else head
    return detail[:ERROR_DETAIL_LIMIT]


def _fail(
    db, tender: Tender, message: str, expected_generation: int, exc: BaseException | None = None
) -> None:
    """Record a terminal failure on the row and publish it - unless this run
    has already been superseded.

    The failing stage may have left uncommitted work; discard it, then record the
    failure. Prior stages are already committed by _advance and survive.

    The rollback is also what makes `failed_stage` truthful: it restores the row
    to its last committed state, so `tender.status` read *after* it is the stage
    _advance last completed — the stage the run was actually in — rather than
    whatever a half-applied update left in the session.

    Gated on `expected_generation` the same way _advance is, and for the same
    reason: TenderCancelled means someone acted on this tender already, and if
    that action was Stop-then-Retry rather than only Stop, a *second* worker
    may already be running the new attempt. Writing FAILED unconditionally
    here would clobber that new run's live status the instant it raced ahead
    of this stale one - the exact bug this whole guard exists to prevent, just
    relocated to the error path instead of the success path.
    """
    db.rollback()

    stage = tender.status.value if tender.status else None
    detail = _error_detail(exc) if exc is not None else message[:ERROR_DETAIL_LIMIT]

    result = db.execute(
        update(Tender)
        .where(Tender.id == tender.id, Tender.run_generation == expected_generation)
        .values(
            status=TenderStatus.FAILED,
            progress_message=message[:500],
            failed_stage=stage,
            error_detail=detail,
            failed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    if result.rowcount == 0:
        logger.info(
            "Tender %s was superseded before this failure could be recorded; discarding it.",
            tender.id,
        )
        return

    db.refresh(tender)
    publish_progress(str(tender.id), TenderStatus.FAILED, message=message[:500])


def _assert_generation(db, tender: Tender, expected_generation: int) -> None:
    """Stop before a stage mutates data for a superseded pipeline run."""
    db.rollback()
    current_generation = db.scalar(
        select(Tender.run_generation).where(
            Tender.id == tender.id,
            Tender.run_generation == expected_generation,
        )
    )
    if current_generation is None:
        raise TenderCancelled()


# --------------------------------------------------------------------------- #
# pipeline                                                                    #
# --------------------------------------------------------------------------- #
def _run_pipeline(db, tender: Tender, expected_generation: int) -> dict:
    content = _read_source(tender)

    # ---- PARSING ----------------------------------------------------------
    _advance(
        db, tender, TenderStatus.PARSING, 5, "Extracting text and tables per page.",
        expected_generation=expected_generation,
    )
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
        expected_generation=expected_generation,
    )
    sectioned = detect_section_boundaries(pages)
    chunks = chunk_sectioned_pages(sectioned)
    guard_against_whole_document_ingestion(chunks)

    # Idempotent re-run: replace this tender's own chunks, nothing else.
    _assert_generation(db, tender, expected_generation)
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
        expected_generation=expected_generation,
    )

    # ---- EXTRACTING (35-60%) + MERGING -----------------------------------
    # run_extraction dedups by clause+description hash as it goes, so MERGING is
    # effectively already done when it returns; we mark it for the timeline.
    _assert_generation(db, tender, expected_generation)
    db.execute(delete(Requirement).where(Requirement.tender_id == tender.id))
    db.commit()
    extraction_result = asyncio.run(run_extraction(db, tender))
    _assert_generation(db, tender, expected_generation)
    created = extraction_result["created"]
    _advance(
        db, tender, TenderStatus.MERGING, 62,
        f"Merged & de-duplicated: {created} unique requirement(s).",
        count=created,
        expected_generation=expected_generation,
    )

    # ---- MATCHING (65-82%) ------------------------------------------------
    match_summary = _run_matching(db, tender, expected_generation)

    # ---- REPORTING (85-90%) ----------------------------------------------
    _advance(
        db, tender, TenderStatus.REPORTING, 85, "Computing marks and coverage.",
        expected_generation=expected_generation,
    )
    report_summary = _compute_report(db, tender)
    _advance(
        db, tender, TenderStatus.REPORTING, 90,
        f"Report ready: {report_summary['captured']:g}/{report_summary['available']:g} "
        "marks auto-covered.",
        expected_generation=expected_generation,
    )

    # ---- ASSEMBLING_FOLDER (92-98%) --------------------------------------
    _advance(
        db, tender, TenderStatus.ASSEMBLING_FOLDER, 92, "Assembling output folder.",
        expected_generation=expected_generation,
    )
    _assemble_folder(db, tender)
    _advance(
        db, tender, TenderStatus.ASSEMBLING_FOLDER, 98, "Output folder assembled.",
        expected_generation=expected_generation,
    )

    # ---- READY_FOR_REVIEW (100%) -----------------------------------------
    # Deliberately NOT terminal for the socket: the run has paused for a human,
    # and the frontend treats READY_FOR_REVIEW as "settled, awaiting review".
    _advance(
        db, tender, TenderStatus.READY_FOR_REVIEW, 100,
        "Analysis complete — ready for review.",
        count=created,
        expected_generation=expected_generation,
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
def _run_matching(db, tender: Tender, expected_generation: int) -> dict:
    """For each requirement that actually needs evidence, semantic-search the
    Evidence Library and record the candidate documents as
    RequirementEvidenceMatch rows, typed by confidence.

    A requirement whose best candidate clears 0.85 gets one AUTO row per
    qualifying document, recorded already ACCEPTED — a confident match doesn't
    make a human click through it, it just has to stay overridable, which
    accept/reject/reassign already handle regardless of a match's starting
    status. 0.60-0.84 gets SUGGESTED rows, left PENDING, because that is the
    band genuinely worth a person's judgment. Below 0.60 we still record the
    single closest document as MISSING so the gap (and what came nearest) is
    visible. Only an empty library (no candidate at all) leaves a requirement
    with no row — there is no document to point one at.

    `evidence_required is False` requirements are skipped before the search
    call — narrative/context clauses the tender itself doesn't ask the bidder
    to prove, so matching them was pure overhead: every qualifying candidate
    became its own PENDING row in the review queue for a requirement no one
    was ever going to attach evidence to. Skipping them here, rather than
    filtering them out of the review queue after the fact, is what actually
    shrinks that queue instead of just hiding the padding.
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
    auto = suggested = missing = no_candidates = not_required = 0

    _advance(
        db, tender, TenderStatus.MATCHING, 65,
        f"Matching {total} requirement(s) to the evidence library.",
        expected_generation=expected_generation,
    )
    if total == 0:
        return {"auto_matches": 0, "suggested_matches": 0, "missing_matches": 0,
                "unmatched_no_library": 0, "not_required": 0}

    for i, req in enumerate(requirements, start=1):
        if not req.evidence_required:
            not_required += 1
            if i % 10 == 0 or i == total:
                percent = 65 + int((i / total) * 17)  # 65 -> 82
                _advance(
                    db, tender, TenderStatus.MATCHING, percent,
                    f"Matched {i} of {total} requirement(s).",
                    expected_generation=expected_generation,
                )
            continue

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
                        # AUTO clears the confident threshold on its own — record it
                        # already accepted instead of PENDING, so it counts toward
                        # coverage immediately and never sits in the human review
                        # queue. A reviewer can still reject or reassign it later;
                        # this only changes where it starts, not what's allowed to
                        # happen to it.
                        review_status=(
                            MatchReviewStatus.ACCEPTED
                            if match_type == MatchType.AUTO
                            else MatchReviewStatus.PENDING
                        ),
                        reviewed_at=datetime.now(timezone.utc) if match_type == MatchType.AUTO else None,
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
                expected_generation=expected_generation,
            )

    return {
        "auto_matches": auto,
        "suggested_matches": suggested,
        "missing_matches": missing,
        "not_required": not_required,
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
def _match_covered(m) -> bool:
    """A single match counts toward coverage when the reviewer accepted it, or it
    auto-matched and has not been rejected. Same rule as _compute_report and
    routes/tenders._requirement_covered, so marks, the coverage column and the
    Required Documents folder can never disagree."""
    return (
        m.review_status == MatchReviewStatus.ACCEPTED
        or (m.match_type == MatchType.AUTO and m.review_status != MatchReviewStatus.REJECTED)
    )


def _requirement_covered(req) -> bool:
    return any(_match_covered(m) for m in req.evidence_matches)


def _coverage_label(req) -> str:
    if not req.evidence_required:
        return "Not required"
    if _requirement_covered(req):
        return "Covered"
    if any(
        m.match_type == MatchType.SUGGESTED and m.review_status == MatchReviewStatus.PENDING
        for m in req.evidence_matches
    ):
        return "Needs review"
    return "Missing"


def _safe_component(name: str, fallback: str = "file") -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("_") or fallback
    return base[:80]


_HEADER_FONT = Font(bold=True)
_WRAP_TOP = Alignment(vertical="top", wrap_text=True)


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        ws.cell(row=1, column=col).font = _HEADER_FONT
    ws.freeze_panes = "A2"


def _set_widths(ws, widths) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def _assemble_folder(db, tender: Tender) -> str:
    """Write OUTPUT_STORAGE_DIR/{tender_id}/ and zip it (TN-OUT-02/03/04).

    The folder holds, exactly as the Implementation Plan's Stage 4 describes:
      - the requirements tracker workbook, multi-sheet: Requirements (the main
        clause-by-clause table), Summary (counts and marks by section and by
        evaluation type), Evidence Matches (per-match confidence and review
        state), and Instructions;
      - the original tender document;
      - a "Required Documents" subfolder holding a copy of every matched
        evidence file (the case studies, methodology and company documents that
        answer a requirement); and
      - summary.json.
    then compresses the lot to OUTPUT_STORAGE_DIR/{tender_id}.zip.

    Rebuilt from scratch on every call — finalize included — so a reviewer who
    rejects a match and re-finalizes does not leave its evidence file orphaned
    in the package. The zip sits beside the folder, not inside it, so clearing
    the folder first is safe. Which files land in Required Documents follows the
    same covered rule as the marks report, so the package and the score agree.
    """
    settings = get_settings()
    out_root = Path(settings.OUTPUT_STORAGE_DIR)
    folder = out_root / str(tender.id)
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    required_dir = folder / "Required Documents"
    required_dir.mkdir(parents=True, exist_ok=True)

    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id)
        .order_by(Requirement.page_number, Requirement.created_at)
        .all()
    )

    # --- copy the matched evidence into Required Documents ----------------- #
    # One copy per document even when it answers several requirements, ordered
    # by first appearance so the folder reads in requirement order.
    doc_relpath: dict = {}          # document.id -> "Required Documents/<file>"
    used_names: set = set()
    missing_files: list = []
    for req in requirements:
        for m in req.evidence_matches:
            if not _match_covered(m):
                continue
            doc = m.document
            if doc is None or doc.id in doc_relpath:
                continue
            src = Path(doc.file_path) if doc.file_path else None
            ext = src.suffix if src else ""
            stem = _safe_component(doc.title or doc.original_filename, "document")
            name = f"{doc.category.value}__{stem}{ext}"
            counter = 1
            while name in used_names:
                counter += 1
                name = f"{doc.category.value}__{stem}_{counter}{ext}"
            used_names.add(name)
            if src and src.is_file():
                try:
                    shutil.copy2(src, required_dir / name)
                    doc_relpath[doc.id] = f"Required Documents/{name}"
                    continue
                except OSError:
                    logger.warning("Could not copy evidence file %s", src)
            # Row exists but the bytes are gone (storage volume reset, usually).
            missing_files.append(str(doc.title or doc.original_filename))

    wb = Workbook()

    # --- Sheet 1: Requirements (the main tracker) -------------------------- #
    #
    # Column order and headings reproduce the client's own tracker exactly, so a
    # generated pack drops straight into their existing process:
    #   Page Number | Section Name | Responsibility | Reference Number |
    #   Clause / Requirement Description | Mandatory | Evaluation Impact | DPL |
    #   PRIME Responsibility | The Tulepaak Responsibility | Joint Responsibility |
    #   Evidence / Document Required | Remarks
    # Values are written VERBATIM (the *_raw columns), so "No/Advisory" and
    # "Financial / Pass-Fail" survive instead of being flattened into the enums the
    # pipeline uses internally. A field the tender does not state is left blank -
    # never "N/A", never guessed.
    #
    # Three VR-Nexus columns follow the tender's own set (Marks, Matched File(s),
    # Coverage), and then one column per extra label this particular tender carried
    # (Requirement.extra_fields), so a tender richer than the template widens the
    # sheet instead of losing data.
    ws = wb.active
    ws.title = "Requirements"

    TENDER_HEADERS = [
        "Page Number",
        "Section Name",
        "Responsibility",
        "Reference Number",
        "Clause / Requirement Description",
        "Mandatory (Yes/No)",
        "Evaluation Impact (Pass/Fail / Technical Score / Financial / Compliance)",
        "DPL",
        "PRIME Responsibility (Yes/No)",
        "The Tulepaak Responsibility (Yes/No)",
        "Joint Responsibility (Yes/No)",
        "Evidence / Document Required",
        "Remarks",
    ]
    VRNEXUS_HEADERS = ["Marks", "Matched File(s)", "Coverage"]

    # Union of every extra label this tender produced, in a stable order.
    extra_keys: list = []
    seen_keys: set = set()
    for r in requirements:
        for key in (r.extra_fields or {}):
            if key not in seen_keys:
                seen_keys.add(key)
                extra_keys.append(str(key))
    extra_keys.sort(key=str.lower)

    main_headers = TENDER_HEADERS + VRNEXUS_HEADERS + extra_keys
    ws.append(main_headers)

    for r in requirements:
        seen_docs: set = set()
        files: list = []
        for m in r.evidence_matches:
            if not _match_covered(m) or m.document is None or m.document.id in seen_docs:
                continue
            seen_docs.add(m.document.id)
            files.append(
                doc_relpath.get(m.document.id, m.document.title or m.document.original_filename)
            )

        # Verbatim first, normalised only as a fallback for rows extracted before
        # the *_raw columns existed.
        page = r.page_label or (str(r.page_number) if r.page_number is not None else "")
        mandatory = r.mandatory_raw or _yn(r.is_mandatory)
        impact = r.evaluation_impact_raw or (
            r.evaluation_impact.value if r.evaluation_impact else ""
        )
        extras = r.extra_fields or {}

        ws.append([
            page,
            r.section_name or "",
            r.responsibility or "",
            r.clause_reference or "",
            (r.description or "")[:32000],  # Excel's per-cell character ceiling
            mandatory,
            impact,
            r.dpl or "",
            r.prime or "",
            r.the_t or "",
            r.joint_responsibility or "",
            r.evidence_description or "",
            r.remarks or "",
            float(r.marks) if r.marks is not None else "",
            "\n".join(files),
            _coverage_label(r),
            *[extras.get(key, "") for key in extra_keys],
        ])

    _style_header(ws, len(main_headers))
    _set_widths(
        ws,
        [10, 26, 16, 14, 60, 14, 24, 8, 14, 16, 14, 34, 34, 8, 32, 13]
        + [22] * len(extra_keys),
    )
    # The prose columns wrap; everything else stays on one line so the sheet scans.
    for row in ws.iter_rows(min_row=2):
        for index in (4, 11, 12, 14):
            if index < len(row):
                row[index].alignment = _WRAP_TOP

    # --- Sheet 2: Summary (counts + marks by section and evaluation type) -- #
    total = len(requirements)
    mandatory = sum(1 for r in requirements if r.is_mandatory is True)
    optional = sum(1 for r in requirements if r.is_mandatory is False)
    marks_available = sum(float(r.marks) for r in requirements if r.marks is not None)
    marks_captured = sum(
        float(r.marks) for r in requirements if r.marks is not None and _requirement_covered(r)
    )
    coverage_pct = round(marks_captured / marks_available * 100, 1) if marks_available > 0 else 0.0
    covered_reqs = sum(1 for r in requirements if _requirement_covered(r))

    ws2 = wb.create_sheet("Summary")
    ws2.append(["Tender", tender.name or tender.original_filename])
    ws2.append(["Reference", tender.reference_id or ""])
    ws2.append(["Issuing authority", tender.issuing_authority or ""])
    ws2.append(["Generated", datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")])
    ws2.append([])
    ws2.append(["Overview", ""])
    overview_start = ws2.max_row
    ws2.append(["Requirements", total])
    ws2.append(["Mandatory", mandatory])
    ws2.append(["Optional", optional])
    ws2.append(["Requirements covered", covered_reqs])
    ws2.append(["Marks available", round(marks_available, 2)])
    ws2.append(["Marks captured", round(marks_captured, 2)])
    ws2.append(["Coverage", f"{coverage_pct}%"])
    ws2.cell(row=overview_start, column=1).font = _HEADER_FONT

    def _grouped(key_of):
        agg: dict = {}
        for r in requirements:
            key = key_of(r)
            a = agg.setdefault(key, {"count": 0, "avail": 0.0, "cap": 0.0})
            a["count"] += 1
            if r.marks is not None:
                a["avail"] += float(r.marks)
                if _requirement_covered(r):
                    a["cap"] += float(r.marks)
        return agg

    ws2.append([])
    ws2.append(["By section", "", "", ""])
    section_header = ws2.max_row
    ws2.append(["Section", "Requirements", "Marks available", "Marks captured"])
    for key, v in sorted(_grouped(lambda r: r.section_name or "Unspecified").items()):
        ws2.append([key, v["count"], round(v["avail"], 2), round(v["cap"], 2)])
    ws2.cell(row=section_header, column=1).font = _HEADER_FONT
    for col in range(1, 5):
        ws2.cell(row=section_header + 1, column=col).font = _HEADER_FONT

    ws2.append([])
    ws2.append(["By evaluation type", "", "", ""])
    eval_header = ws2.max_row
    ws2.append(["Evaluation type", "Requirements", "Marks available", "Marks captured"])
    for key, v in sorted(
        _grouped(
            lambda r: r.evaluation_impact_raw
            or (r.evaluation_impact.value if r.evaluation_impact else "Unspecified")
        ).items()
    ):
        ws2.append([key, v["count"], round(v["avail"], 2), round(v["cap"], 2)])
    ws2.cell(row=eval_header, column=1).font = _HEADER_FONT
    for col in range(1, 5):
        ws2.cell(row=eval_header + 1, column=col).font = _HEADER_FONT
    _set_widths(ws2, [26, 16, 16, 16])

    # --- Sheet 3: Evidence Matches (per-match detail) ---------------------- #
    ws3 = wb.create_sheet("Evidence Matches")
    ws3.append(
        ["Requirement Clause", "Requirement (excerpt)", "Matched Document",
         "Similarity", "Match Type", "Review Status"]
    )
    match_total = 0
    for r in requirements:
        for m in r.evidence_matches:
            match_total += 1
            doc = m.document
            ws3.append([
                r.clause_reference or "",
                (r.description or "")[:200],
                (doc.title or doc.original_filename) if doc else "",
                float(m.confidence_score) if m.confidence_score is not None else "",
                m.match_type.value,
                m.review_status.value,
            ])
    _style_header(ws3, 6)
    _set_widths(ws3, [16, 50, 32, 11, 13, 14])

    # --- Sheet 4: Instructions -------------------------------------------- #
    ws4 = wb.create_sheet("Instructions")
    for line in [
        "How to use this tender analysis pack",
        "",
        "This workbook and folder were generated by VR-Nexus from the tender named on the",
        "Summary sheet. They are a decision aid for your bid team, not a substitute for",
        "reading the tender.",
        "",
        "Requirements sheet",
        "  One row per requirement VR-Nexus extracted, in document order. 'Coverage' reads:",
        "    Covered      - answered by an accepted or auto-matched document (marks captured).",
        "    Needs review - a suggested match is waiting for a reviewer's decision.",
        "    Missing      - no document in your library answers this requirement yet.",
        "    Not required - the requirement needs no supporting document.",
        "  'Matched File(s)' points into the Required Documents folder beside this workbook.",
        "",
        "Summary sheet",
        "  Counts and marks totalled overall, by tender section, and by evaluation type.",
        "  Marks captured follows the same covered rule as the Coverage column.",
        "",
        "Evidence Matches sheet",
        "  Every candidate document VR-Nexus found for each requirement, with its similarity",
        "  score, match type and the reviewer's decision.",
        "",
        "Required Documents folder",
        "  A copy of each matched case study, methodology and company document, ready to",
        "  attach to your submission. Files are named <category>__<document title>.",
        "",
        "Review before you rely on it",
        "  VR-Nexus proposes matches; a person confirms them. Coverage reflects the matches",
        "  accepted at the time this pack was generated. Re-finalize the tender in VR-Nexus",
        "  to regenerate this pack after any further review.",
    ]:
        ws4.append([line])
    ws4.column_dimensions["A"].width = 90

    wb.save(str(folder / "requirements_and_matches.xlsx"))

    # --- copy the original tender document into the folder root ------------ #
    if tender.file_path:
        tender_src = Path(tender.file_path)
        if tender_src.is_file():
            try:
                shutil.copy2(tender_src, folder / (tender.original_filename or tender_src.name))
            except OSError:
                logger.warning("Could not copy the source tender %s", tender_src)

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
        "requirements_total": total,
        "requirements_covered": covered_reqs,
        "evidence_matches_total": match_total,
        "evidence_files_included": len(doc_relpath),
        "missing_evidence_files": missing_files,
        "marks_available": (
            float(tender.total_marks_available) if tender.total_marks_available is not None else None
        ),
        "marks_captured": (
            float(tender.total_marks_captured) if tender.total_marks_captured is not None else None
        ),
        "coverage_percent": coverage_pct,
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
def enqueue(tender_id: uuid.UUID | str, run_generation: int):
    """Queue a pipeline run, tagged with the tender's current run_generation.

    Called by the API's upload endpoint (generation 0, the row's default) and
    by reprocess (after it has already bumped the counter). The generation is
    passed explicitly rather than left for the task to read off the row itself
    at start - see run_tender_pipeline's own docstring for why that matters.
    """
    return run_tender_pipeline.delay(str(tender_id), run_generation)
