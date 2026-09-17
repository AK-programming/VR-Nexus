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
    EXTRACTING        35-60 run_extraction() — owns its own progress + normalised-hash dedup
    MERGING           62    embedding-similarity near-duplicate merge (see requirement_merge.py) —
                             catches a restatement extraction's own hash dedup does not
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
from typing import Optional

import fitz  # PyMuPDF - also used by services/pdf_extraction.py to read tender PDFs
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy import delete, select, update

from app.celery_app import celery_app  # noqa: F401  (ensures the app is configured)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.enums import MatchReviewStatus, MatchType, TenderStatus, UsagePurpose
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.services.chunking import (
    chunk_sectioned_pages,
    detect_section_boundaries,
    guard_against_whole_document_ingestion,
)
from app.services.extraction import (
    TenderCancelled,
    extract_tender_metadata,
    extraction_model,
    run_extraction,
)
from app.services.library.search import search
from app.services.requirement_merge import merge_duplicates
from app.services.section_triage import (
    EXTRACTED_KINDS as TRIAGE_EXTRACTED_KINDS,
    load_outcome as load_triage_outcome,
    triage_pages,
)
from app.models.user import User
from app.schemas.excel_template import ExcelTemplate, FIXED_COLUMN_KEYS
from app.services.pdf_extraction import extract_pdf_pages
from app.services.progress import publish_progress
from app.services.usage_tracking import compute_tender_usage, record_usage

logger = logging.getLogger(__name__)

# Match thresholds, taken verbatim from the MatchType enum's own definitions in
# app/models/enums.py so the two can never drift:
#   AUTO       confidence >= 0.65
#   SUGGESTED  0.60 - 0.64
#   MISSING    < 0.60
#
# SUGGESTED_MATCH_FLOOR was 0.50 and MATCH_TOP_K was 5. Raised the floor and
# halved top_k because every qualifying candidate becomes its own PENDING row a
# person has to click through, and at the old settings a single requirement
# could hand back up to 5 near-duplicate suggestions clustered a few points
# apart — reviewers were working through hundreds of rows, most of them low-
# value. Fewer, better candidates below; AUTO rows below the review queue
# entirely (see the review_status change in _run_matching).
#
# AUTO_MATCH_THRESHOLD was 0.85 until a real-corpus check (two tenders,
# hundreds of matches) showed the search's own cosine similarity — pgvector
# over fastembed's BAAI/bge-base-en-v1.5, see library/search.py — never
# reaches 0.85 for a genuinely correct match. A requirement and a case study
# describe the same deliverable in different words; that tops out around
# 0.65-0.72 (measured), and only near-verbatim text ever clears 0.85. At 0.85
# the AUTO tier was unreachable by construction, so nothing ever auto-
# accepted and every qualifying candidate landed PENDING in the review queue
# regardless of how confident it actually was. 0.65 was picked by sampling:
# matches below it are dominated by generic procedural/compliance clauses
# keyed to a case study by shared boilerplate vocabulary rather than genuine
# topical overlap (false positives), while 0.65+ was consistently the tender's
# own subject matter matching the right case study. Re-check this the same way
# (sample real matches by score band) before moving it again — it is
# calibrated to this embedding model and this library's content, not a
# universal constant.
AUTO_MATCH_THRESHOLD = 0.65
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

    # ---- SECTION TRIAGE (one cheap call, before the expensive pass) -------
    # Nearly half of one reference tender was contract conditions and table of
    # contents, which no analyst tracker draws a single row from. The rewritten
    # extraction prompt correctly returns nothing for those pages, but we were
    # still paying a full call per chunk to be told so. This classifies the
    # document's page spans once and lets run_extraction skip the spans that
    # cannot contain a bid action.
    #
    # Chunking above is untouched: every page is still chunked and stored, so
    # the "no page is silently dropped" guarantee holds. What changes is which
    # chunks are SENT, and that decision is recorded on the tender and shown in
    # the workbook. Any failure or implausible answer falls back to extracting
    # everything (see section_triage's module docstring).
    # Resolved once, and the same provider+model extraction itself will use, so
    # the scope decision and the extraction it scopes cannot end up on different
    # models if an admin changes the Settings selection mid-run.
    triage_model = extraction_model(db)
    triage = asyncio.run(triage_pages(pages, triage_model))
    tender.section_triage = triage.as_json()
    db.commit()
    if triage.input_tokens or triage.output_tokens:
        record_usage(
            db,
            model=triage_model["model"],
            purpose=UsagePurpose.TENDER_EXTRACTION,
            input_tokens=triage.input_tokens,
            output_tokens=triage.output_tokens,
            latency_ms=triage.latency_ms,
            tender_id=tender.id,
            user_id=tender.uploaded_by,
        )
    logger.info("Tender %s section triage: %s", tender.id, triage.reason)

    # ---- EXTRACTING (35-60%) ---------------------------------------------
    _assert_generation(db, tender, expected_generation)
    # duplicate_of_id is a self-FK with no ON DELETE clause, so once the MERGING
    # stage below has tombstoned a duplicate, a bulk DELETE of this tender's
    # requirements can violate it: the rows go in no guaranteed order, and a
    # tombstone still pointing at its keeper blocks the keeper's deletion.
    # Clearing the pointers first makes the delete order irrelevant.
    db.execute(
        update(Requirement)
        .where(Requirement.tender_id == tender.id, Requirement.duplicate_of_id.isnot(None))
        .values(duplicate_of_id=None)
    )
    db.execute(delete(Requirement).where(Requirement.tender_id == tender.id))
    db.commit()
    extraction_result = asyncio.run(run_extraction(db, tender))
    _assert_generation(db, tender, expected_generation)
    created = extraction_result["created"]

    # Surface a triage failure the same way a chunk failure is surfaced above -
    # "found nothing to exclude" and "excluded fraction over the ceiling" are
    # both legitimate, silent outcomes (a short or uniformly bid-relevant
    # tender genuinely has nothing post-award to strip), but "the call failed"
    # or "no usable spans" mean triage never got a real answer and the whole
    # document was extracted, unfiltered, as a fallback - the same failure
    # shape as a chunk falling back to "nothing extracted", and worth the same
    # visibility rather than being findable only in the worker log.
    if not triage.applied and ("failed" in triage.reason.lower() or "no usable spans" in triage.reason.lower()):
        triage_note = f"Section triage did not run: {triage.reason}"
        tender.extraction_warnings = (
            f"{tender.extraction_warnings} {triage_note}"
            if tender.extraction_warnings
            else triage_note
        )
        db.commit()

    # ---- MERGING (62%) ----------------------------------------------------
    # Real work now, not just a timeline marker. run_extraction's own dedup is a
    # normalised hash, so it catches a restatement differing by punctuation but
    # not one differing by a whole trailing clause - and tenders restate
    # obligations constantly (one RFP lists its eligibility criteria twice, 60
    # pages apart, which shipped as 16 rows for 7 requirements carrying two
    # different coverage verdicts). This pass groups them by embedding
    # similarity and folds each group into one row.
    #
    # Before MATCHING deliberately: merging first means the evidence search runs
    # once per obligation instead of once per copy, and no two copies of one
    # obligation can come back with different verdicts.
    merge_result = merge_duplicates(db, tender.id)
    _assert_generation(db, tender, expected_generation)
    if merge_result.merged_away:
        merge_message = (
            f"Merged {merge_result.merged_away} restated requirement(s) into "
            f"{merge_result.groups} obligation(s): {merge_result.remaining} unique."
        )
    else:
        merge_message = f"De-duplicated: {created} unique requirement(s)."
    _advance(
        db, tender, TenderStatus.MERGING, 62, merge_message,
        count=merge_result.remaining,
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
    meta = asyncio.run(
        extract_tender_metadata(sample, db=db, tender_id=tender.id, user_id=tender.uploaded_by)
    )
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

    # The tender's own stated scoring totals, kept as an independent check on
    # the marks extraction sums up per requirement. See _marks_reconciliation.
    for column, key in (
        ("stated_technical_marks", "technical_marks_total"),
        ("passing_technical_score", "passing_technical_score"),
    ):
        number = _parse_number(meta.get(key))
        if number is not None:
            setattr(tender, column, number)

    db.commit()


#: Signs that a metadata string is a money amount rather than a mark count.
#: Worth guarding explicitly: "PKR 25,000,000" parses to 25.0 under a naive
#: first-number read, because the comma ends the digit run, and 25 sits happily
#: inside any plausible marks range. That would then be compared against the
#: real extracted total and reported as "marks look incomplete" - a confident
#: warning about the wrong thing, which is worse than no warning.
_MONEY_HINT_RE = re.compile(r"(?i)\b(pkr|usd|rs|eur|gbp|inr|million|billion|crore|lakh)\b|[$£€]|\d,\d{3}")


def _parse_number(value) -> float | None:
    """First number in a scoring metadata string ("100", "100 marks", "70%"),
    or None.

    Bounded to a plausible marks range and rejected outright when the string
    looks like currency, so a field the model filled in wrongly is dropped
    rather than becoming a reconciliation baseline that flags a correct run as
    inconsistent. Dropping it means the check is skipped, which is the safe
    failure: no claim beats a false claim.
    """
    text = str(value or "")
    if _MONEY_HINT_RE.search(text):
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group())
    except ValueError:
        return None
    # Technical scoring totals in real tenders are 100, occasionally 1000.
    # Anything larger is a mis-parse, not a mark count.
    return number if 0 < number <= 1000 else None


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
        .filter(Requirement.tender_id == tender.id, Requirement.duplicate_of_id.is_(None))
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
    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id, Requirement.duplicate_of_id.is_(None))
        .all()
    )

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
_WARNING_FONT = Font(bold=True, color="9C4221")  # amber-brown, readable on white without looking like an error
_WRAP_TOP = Alignment(vertical="top", wrap_text=True)


def _style_header(ws, ncols: int) -> None:
    for col in range(1, ncols + 1):
        ws.cell(row=1, column=col).font = _HEADER_FONT
    ws.freeze_panes = "A2"


def _set_widths(ws, widths) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


# --- Excel export customization (see app/schemas/excel_template.py) -------- #
#
# FIXED_COLUMN_REGISTRY is the stable key -> (default label, width, wrap,
# getter) mapping for every fixed column the assembler can produce. It is
# the single source of truth both the platform-default layout below and a
# user's ExcelTemplate draw from, so a template's `key` values always mean
# the same thing whichever tender it's applied to. `getter` reads from the
# per-row `values` dict built once per requirement in _assemble_folder
# (see _row_values), not from the Requirement object directly, so the
# registry itself has no per-row computation to duplicate.
FIXED_COLUMN_REGISTRY: dict[str, dict] = {
    "page_number": {"label": "Page Number", "width": 10, "wrap": False},
    "section_name": {"label": "Section Name", "width": 26, "wrap": False},
    "responsibility": {"label": "Responsibility", "width": 16, "wrap": False},
    "reference_number": {"label": "Reference Number", "width": 14, "wrap": False},
    "description": {"label": "Clause / Requirement Description", "width": 60, "wrap": True},
    "mandatory": {"label": "Mandatory (Yes/No)", "width": 14, "wrap": False},
    "evaluation_impact": {
        "label": "Evaluation Impact (Pass/Fail / Technical Score / Financial / Compliance)",
        "width": 24,
        "wrap": False,
    },
    # Derived from the extracted owner hint - see OWNER_COLUMNS below. Labels
    # match the analyst-authored tracker for a solo bid.
    "owner_bd": {"label": "BD / Bid Management", "width": 14, "wrap": False},
    "owner_technical": {"label": "Technical / Delivery", "width": 14, "wrap": False},
    "owner_finance_legal": {"label": "Finance / Legal / Admin", "width": 14, "wrap": False},
    "owner_hr": {"label": "HR / Resource Management", "width": 14, "wrap": False},
    "owner_joint": {"label": "Joint / Multiple", "width": 12, "wrap": False},
    # Legacy, from when one consortium's partner names were hardcoded as
    # extraction fields. Kept so tenders already in the database still render
    # theirs; extraction no longer writes them, and the default layout drops
    # them when empty (see CONDITIONAL_FIXED_KEYS).
    "dpl": {"label": "DPL", "width": 8, "wrap": False},
    "prime": {"label": "PRIME Responsibility (Yes/No)", "width": 14, "wrap": False},
    "the_t": {"label": "The Tulepaak Responsibility (Yes/No)", "width": 16, "wrap": False},
    "joint_responsibility": {"label": "Joint Responsibility (Yes/No)", "width": 14, "wrap": False},
    "evidence_description": {"label": "Evidence / Document Required", "width": 34, "wrap": True},
    "remarks": {"label": "Remarks", "width": 34, "wrap": True},
    "marks": {"label": "Marks", "width": 8, "wrap": False},
    "matched_files": {"label": "Matched File(s)", "width": 32, "wrap": True},
    "coverage": {"label": "Coverage", "width": 13, "wrap": False},
}


def _resolve_excel_template(db, tender: Tender) -> Optional[ExcelTemplate]:
    """Which template applies to this tender's output, per the client's own
    two-level answer: a per-tender override (set at the "is the format OK?"
    check) beats the user's saved account default, which beats the platform
    default (None - the original fixed layout, unchanged).

    Malformed/stale JSON on either column is treated as "not set" rather than
    failing the whole run - a template is a display preference, never a
    reason an already-extracted tender can't produce its tracker."""
    if tender.excel_template_override:
        try:
            return ExcelTemplate.model_validate(tender.excel_template_override)
        except Exception:
            logger.warning("Tender %s has an invalid excel_template_override; ignoring it.", tender.id)

    if tender.uploaded_by:
        user = db.query(User).filter(User.id == tender.uploaded_by).first()
        if user and user.default_excel_template:
            try:
                return ExcelTemplate.model_validate(user.default_excel_template)
            except Exception:
                logger.warning("User %s has an invalid default_excel_template; ignoring it.", user.id)

    return None


#: owner_hint (app/services/extraction.py's OwnerHint) -> the workbook column
#: that gets a "Yes".
#:
#: Replaces the hardcoded DPL / PRIME / The Tulepaak trio, which were one
#: specific consortium's partner names baked into the extraction schema and
#: 100% empty on any tender where DPL bid alone. A model can reason about
#: "which function owns this" and cannot possibly know a partner's name, so the
#: automatic columns are functional and the partner columns are manual.
#:
#: For a CONSORTIUM bid, the bid team adds partner-named columns through the
#: Excel template's `added_columns`, which renders them blank for hand
#: assignment - the same thing the analyst did by hand on the reference tender.
#: This is the honest split: derive what is derivable, leave the rest editable.
OWNER_COLUMNS: dict[str, str] = {
    "BD": "owner_bd",
    "Technical": "owner_technical",
    "Finance-Legal": "owner_finance_legal",
    "HR": "owner_hr",
    "Joint": "owner_joint",
}


def _owner_cells(responsibility: Optional[str]) -> dict[str, str]:
    """One "Yes" and the rest "No", from the requirement's owner hint.

    Exactly one, because `owner_hint` is single-valued. The analyst's own sheet
    marks SEVERAL departments on some rows ("Submit all listed forms" is BD,
    Technical, Finance and HR at once), so these columns are a starting point a
    bid manager corrects, not a reproduction of that judgement. An unrecognised
    or missing hint leaves every column blank rather than guessing "BD", so a
    reviewer can see the difference between "nobody assigned" and "assigned to
    BD".
    """
    column = OWNER_COLUMNS.get((responsibility or "").strip())
    if column is None:
        return {key: "" for key in OWNER_COLUMNS.values()}
    return {key: ("Yes" if key == column else "No") for key in OWNER_COLUMNS.values()}


def _row_values(
    r: Requirement,
    files: list[str],
    demoted_extra_keys: Optional[set] = None,
) -> dict[str, object]:
    """One dict per requirement row, keyed by FIXED_COLUMN_REGISTRY's stable
    keys - built once and read by both the default layout and a custom
    template, so the two can never compute a cell differently.

    `demoted_extra_keys` are extra fields too sparse to earn their own column
    (see the fill-rate gate in the workbook writer). Their values are appended
    to Remarks as "label: value" so the data survives without widening every
    row by a column that is blank almost everywhere."""
    page = r.page_label or (str(r.page_number) if r.page_number is not None else "")
    mandatory = r.mandatory_raw or _yn(r.is_mandatory)
    impact = r.evaluation_impact_raw or (r.evaluation_impact.value if r.evaluation_impact else "")

    remarks = r.remarks or ""
    if demoted_extra_keys:
        folded = [
            f"{key}: {str(value).strip()}"
            for key, value in sorted((r.extra_fields or {}).items())
            if key in demoted_extra_keys and str(value or "").strip()
        ]
        if folded:
            remarks = "\n".join([remarks, *folded]) if remarks else "\n".join(folded)

    return {
        "page_number": page,
        "section_name": r.section_name or "",
        "responsibility": r.responsibility or "",
        "reference_number": r.clause_reference or "",
        "description": (r.description or "")[:32000],
        "mandatory": mandatory,
        "evaluation_impact": impact,
        **_owner_cells(r.responsibility),
        "dpl": r.dpl or "",
        "prime": r.prime or "",
        "the_t": r.the_t or "",
        "joint_responsibility": r.joint_responsibility or "",
        "evidence_description": r.evidence_description or "",
        "remarks": remarks,
        "marks": float(r.marks) if r.marks is not None else "",
        "matched_files": "\n".join(files),
        "coverage": _coverage_label(r),
    }


def _build_template_columns(
    template: ExcelTemplate, extra_keys: list[str]
) -> list[dict]:
    """Turns a user's ExcelTemplate into the concrete ordered column list to
    render: [{key, label, wrap, width, is_extra, is_added}]. Unknown/deleted
    keys (an extra field from a different tender, a fixed key that no longer
    exists) are silently dropped rather than erroring - a saved template
    should keep working across tenders that don't all share the same extra
    fields, per the client's own "different format for the different
    [tenders] but may be the same tender" answer.

    columns=[] (the user never touched the customizer, or cleared every
    column back out) falls back to the platform's own default column set,
    same as no template at all - customizing is additive, never a way to
    accidentally end up with an empty sheet.
    """
    resolved: list[dict] = []
    configured = [c for c in template.columns if c.visible]
    source = configured if template.columns else []

    if not source:
        # No explicit column list: keep the platform's default order/labels,
        # but still honour delete_empty_rows / added_columns on their own.
        for key in FIXED_COLUMN_KEYS:
            spec = FIXED_COLUMN_REGISTRY[key]
            resolved.append({"key": key, "label": spec["label"], "wrap": spec["wrap"], "width": spec["width"], "is_extra": False})
        for key in extra_keys:
            resolved.append({"key": key, "label": key, "wrap": False, "width": 22, "is_extra": True})
        return resolved

    for col in source:
        if col.key in FIXED_COLUMN_REGISTRY:
            spec = FIXED_COLUMN_REGISTRY[col.key]
            resolved.append(
                {
                    "key": col.key,
                    "label": col.label or spec["label"],
                    "wrap": spec["wrap"],
                    "width": spec["width"],
                    "is_extra": False,
                }
            )
        elif col.key in extra_keys:
            resolved.append(
                {"key": col.key, "label": col.label or col.key, "wrap": False, "width": 22, "is_extra": True}
            )
        # else: references a field this tender doesn't have - dropped.

    return resolved


_USAGE_PURPOSE_LABELS = {
    "tender_extraction": "Tender extraction",
    "tender_metadata": "Tender metadata",
    "library_tagging": "Library auto-tagging",
    "library_ask": "Library Ask",
}

# api_usage_report.pdf's palette - the app's own brand tokens (see
# myapp/src/index.css's @theme block), as 0-1 fitz RGB tuples rather than the
# hex strings the frontend uses: PyMuPDF's drawing/text calls take floats.
_PDF_BRAND = (232 / 255, 21 / 255, 27 / 255)        # --color-brand-500
_PDF_BRAND_DARK = (163 / 255, 15 / 255, 20 / 255)   # --color-brand-700
_PDF_INK = (0.10, 0.10, 0.12)
_PDF_MUTED = (0.45, 0.45, 0.48)
_PDF_HAIRLINE = (0.88, 0.89, 0.91)
_PDF_ROW_ALT = (0.965, 0.965, 0.97)
_PDF_HEADER_BG = (0.98, 0.90, 0.90)

# Same PNG the frontend serves as /vr-nexus-logo.png (myapp/public/), copied
# in here rather than reached over HTTP: this runs in the worker/api
# container, which has no reason to depend on the frontend being up (or even
# deployed) to assemble a tender's output folder. Its true aspect ratio
# (682x416 px) is baked into the constant below rather than read from the
# file at render time - one fixed emblem, not arbitrary uploaded art.
_LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "vr-nexus-logo.png"
_LOGO_ASPECT = 682 / 416


def _fmt_usage_cost(value: float) -> str:
    """Mirrors formatCostUsd in myapp/src/lib/formatting.ts: enough
    significant digits to show a sub-cent call without printing "$0.00" for
    almost every real row, collapsing to plain cents once the amount no
    longer needs the extra precision."""
    if not value:
        return "$0.00"
    abs_value = abs(value)
    decimals = 4 if abs_value < 0.01 else 3 if abs_value < 1 else 2
    return f"${value:.{decimals}f}"


def _fmt_usage_ms(value: float) -> str:
    """Mirrors formatDurationMs in myapp/src/lib/formatting.ts, minus the
    minutes tier: a single tender's total latency realistically tops out
    well under a minute even for a large document."""
    if value < 1000:
        return f"{value:.0f}ms"
    return f"{value / 1000:.1f}s"


def _fmt_usage_int(value: int) -> str:
    return f"{value:,}"


def _pdf_truncate_to_width(text: str, fontname: str, fontsize: float, max_width: float) -> str:
    """Chops `text` to fit `max_width`, adding an ellipsis - for the tender
    name in the header (some tender filenames are full sentences) and the
    bar charts' per-purpose x-axis labels (narrow once there are 3-4
    purposes sharing one page-width chart)."""
    if fitz.get_text_length(text, fontname=fontname, fontsize=fontsize) <= max_width:
        return text
    ellipsis = "..."
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ellipsis if lo > 0 else ellipsis


def _pdf_draw_hline(page, x0: float, x1: float, y: float, color=_PDF_HAIRLINE, width: float = 0.75) -> None:
    """Draws and commits immediately - see _pdf_fill_rect's note on why."""
    shape = page.new_shape()
    shape.draw_line((x0, y), (x1, y))
    shape.finish(color=color, width=width)
    shape.commit()


def _pdf_fill_rect(page, rect: "fitz.Rect", color) -> None:
    """A Shape's fills/strokes only actually paint onto the page at
    .commit() - queuing several fills on one shared Shape for the whole page
    and committing once at the end (the obvious way to write this) paints
    all of them LAST, on top of any text already inserted earlier via
    insert_text (which paints immediately, unlike Shape). That silently
    blanks out every zebra-striped/header row's text behind its own
    background fill. Each call here is therefore its own Shape, committed
    immediately, so painting stays in the same top-to-bottom order the code
    below reads in."""
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(fill=color, color=color, width=0)
    shape.commit()


def _write_usage_report_pdf(path: Path, tender: Tender, usage) -> None:
    """Writes api_usage_report.pdf: a one-page visual summary of what this
    tender's own Anthropic API calls cost - the VR-Nexus mark, a totals
    table, a by-purpose breakdown table, then a pair of bar charts (calls
    and estimated cost, each by purpose) - for whoever opens the downloaded
    ZIP without going back into VR-Nexus. `usage` is a TenderUsageOut from
    services/usage_tracking.compute_tender_usage - the same numbers the
    Tender Review page's usage badge shows, so the bundled report and the
    in-app figure can never disagree.

    Built directly with PyMuPDF (`fitz`) rather than adding a reportlab/
    matplotlib dependency just for one summary page: PyMuPDF is already a
    hard dependency for reading the tender PDF itself (see
    services/pdf_extraction.py), and a table plus two bar charts is a few
    dozen draw_rect/insert_text calls - well within what its drawing API is
    built for.

    A separate file rather than another sheet in requirements_and_matches.xlsx:
    that workbook is the requirements tracker a bid team edits and shares
    onward, while this is a cost/ops summary for whoever is tracking API
    spend - keeping them apart means the tracker never grows a section no
    reviewer asked for.
    """
    page_w, page_h = 595, 842  # A4 at 72dpi, matching the tender PDFs this sits beside
    margin = 42
    content_w = page_w - 2 * margin

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    y = margin

    # --- header: logo + title ------------------------------------------- #
    logo_h = 46
    logo_w = logo_h * _LOGO_ASPECT
    if _LOGO_PATH.is_file():
        page.insert_image(fitz.Rect(margin, y, margin + logo_w, y + logo_h), filename=str(_LOGO_PATH))
    title_x = margin + logo_w + 14
    page.insert_text((title_x, y + 20), "API Usage Report", fontsize=18, fontname="hebo", color=_PDF_INK)
    page.insert_text((title_x, y + 36), "VR-Nexus Tender Intelligence", fontsize=8.5, fontname="helv", color=_PDF_MUTED)
    y += logo_h + 14

    tender_label = _pdf_truncate_to_width(
        f"Tender: {tender.name or tender.original_filename or tender.id}", "helv", 10.5, content_w,
    )
    page.insert_text((margin, y), tender_label, fontsize=10.5, fontname="helv", color=_PDF_INK)
    y += 15
    page.insert_text(
        (margin, y),
        f"Generated {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}",
        fontsize=9, fontname="helv", color=_PDF_MUTED,
    )
    y += 14
    _pdf_draw_hline(page, margin, page_w - margin, y, color=_PDF_BRAND, width=1.4)
    y += 26

    # --- totals table ------------------------------------------------------ #
    page.insert_text((margin, y), "Totals", fontsize=12.5, fontname="hebo", color=_PDF_INK)
    y += 12
    row_h = 20
    col1_w = content_w * 0.58
    totals_rows = [
        ("Total calls", _fmt_usage_int(usage.total_calls)),
        ("Input tokens", _fmt_usage_int(usage.input_tokens)),
        ("Output tokens", _fmt_usage_int(usage.output_tokens)),
        ("Total tokens", _fmt_usage_int(usage.total_tokens)),
        ("Estimated cost (USD)", _fmt_usage_cost(usage.cost_usd)),
        ("Total latency", _fmt_usage_ms(usage.total_latency_ms)),
        ("Average latency per call", _fmt_usage_ms(usage.avg_latency_ms)),
    ]
    table_top = y
    for i, (label, value) in enumerate(totals_rows):
        row_y = y + i * row_h
        if i % 2 == 1:
            _pdf_fill_rect(page, fitz.Rect(margin, row_y, margin + content_w, row_y + row_h), _PDF_ROW_ALT)
        page.insert_text((margin + 8, row_y + row_h - 6), label, fontsize=9.5, fontname="helv", color=_PDF_INK)
        page.insert_text((margin + col1_w, row_y + row_h - 6), value, fontsize=9.5, fontname="hebo", color=_PDF_INK)
    table_bottom = table_top + len(totals_rows) * row_h
    _pdf_draw_hline(page, margin, margin + content_w, table_bottom)
    y = table_bottom + 28

    # --- by-purpose table ---------------------------------------------------#
    has_purpose_rows = len(usage.by_purpose) > 0
    if has_purpose_rows:
        page.insert_text((margin, y), "By purpose", fontsize=12.5, fontname="hebo", color=_PDF_INK)
        y += 12

        cols = [
            ("Purpose", 0.30),
            ("Calls", 0.12),
            ("Input tok.", 0.15),
            ("Output tok.", 0.15),
            ("Cost", 0.14),
            ("Avg latency", 0.14),
        ]
        col_x = [margin]
        for _, frac in cols:
            col_x.append(col_x[-1] + frac * content_w)

        header_h = 20
        _pdf_fill_rect(page, fitz.Rect(margin, y, margin + content_w, y + header_h), _PDF_HEADER_BG)
        for i, (label, _) in enumerate(cols):
            align_right = i > 0
            tw = fitz.get_text_length(label, fontname="hebo", fontsize=8.5) if align_right else 0
            tx = (col_x[i + 1] - 8 - tw) if align_right else col_x[i] + 8
            page.insert_text((tx, y + header_h - 6), label, fontsize=8.5, fontname="hebo", color=_PDF_BRAND_DARK)
        y += header_h

        purpose_row_h = 19
        table_top2 = y
        for i, p in enumerate(usage.by_purpose):
            row_y = y + i * purpose_row_h
            if i % 2 == 1:
                _pdf_fill_rect(page, fitz.Rect(margin, row_y, margin + content_w, row_y + purpose_row_h), _PDF_ROW_ALT)
            purpose_value = getattr(p.purpose, "value", p.purpose)
            values = [
                _USAGE_PURPOSE_LABELS.get(purpose_value, str(purpose_value)),
                _fmt_usage_int(p.calls),
                _fmt_usage_int(p.input_tokens),
                _fmt_usage_int(p.output_tokens),
                _fmt_usage_cost(p.cost_usd),
                _fmt_usage_ms(p.avg_latency_ms),
            ]
            for ci, val in enumerate(values):
                align_right = ci > 0
                fname = "hebo" if ci == 0 else "helv"
                if align_right:
                    tw = fitz.get_text_length(val, fontname=fname, fontsize=9)
                    tx = col_x[ci + 1] - 8 - tw
                else:
                    tx = col_x[ci] + 8
                page.insert_text((tx, row_y + purpose_row_h - 6), val, fontsize=9, fontname=fname, color=_PDF_INK)
        table_bottom2 = table_top2 + len(usage.by_purpose) * purpose_row_h
        _pdf_draw_hline(page, margin, margin + content_w, table_bottom2)
        y = table_bottom2 + 32
    else:
        page.insert_text((margin, y), "By purpose", fontsize=12.5, fontname="hebo", color=_PDF_INK)
        y += 16
        page.insert_text(
            (margin, y), "No individual API calls have been recorded for this tender yet.",
            fontsize=9.5, fontname="helv", color=_PDF_MUTED,
        )
        y += 30

    # --- bar charts: calls and cost, each by purpose ------------------------#
    if has_purpose_rows:
        page.insert_text((margin, y), "Usage by purpose", fontsize=12.5, fontname="hebo", color=_PDF_INK)
        y += 16

        chart_h = 150
        gap = 20
        chart_w = (content_w - gap) / 2
        charts = [
            ("Calls", [p.calls for p in usage.by_purpose], _fmt_usage_int),
            ("Estimated cost (USD)", [p.cost_usd for p in usage.by_purpose], _fmt_usage_cost),
        ]
        labels = [
            _USAGE_PURPOSE_LABELS.get(getattr(p.purpose, "value", p.purpose), str(getattr(p.purpose, "value", p.purpose)))
            for p in usage.by_purpose
        ]

        plot_bottom = y
        for ci, (chart_title, values, fmt) in enumerate(charts):
            cx0 = margin + ci * (chart_w + gap)
            cx1 = cx0 + chart_w
            page.insert_text((cx0, y), chart_title, fontsize=9.5, fontname="hebo", color=_PDF_INK)
            plot_top = y + 10
            plot_bottom = plot_top + chart_h
            _pdf_draw_hline(page, cx0, cx1, plot_bottom, color=_PDF_HAIRLINE, width=1)

            max_val = max(values) if values and max(values) > 0 else 1
            n = len(values)
            slot_w = (cx1 - cx0) / max(n, 1)
            bar_w = min(slot_w * 0.5, 46)
            for bi, v in enumerate(values):
                bar_h = (v / max_val) * (chart_h - 26) if max_val else 0
                slot_cx = cx0 + slot_w * (bi + 0.5)
                by0 = plot_bottom - bar_h
                if bar_h > 0:
                    _pdf_fill_rect(page, fitz.Rect(slot_cx - bar_w / 2, by0, slot_cx + bar_w / 2, plot_bottom), _PDF_BRAND)
                val_text = fmt(v)
                tw = fitz.get_text_length(val_text, fontname="hebo", fontsize=8)
                page.insert_text((slot_cx - tw / 2, by0 - 5), val_text, fontsize=8, fontname="hebo", color=_PDF_INK)
                label = _pdf_truncate_to_width(labels[bi], "helv", 7.5, slot_w - 4)
                lw = fitz.get_text_length(label, fontname="helv", fontsize=7.5)
                page.insert_text((slot_cx - lw / 2, plot_bottom + 12), label, fontsize=7.5, fontname="helv", color=_PDF_MUTED)
        y = plot_bottom + 30

    # --- footer --------------------------------------------------------- #
    footer_y = page_h - margin + 4
    _pdf_draw_hline(page, margin, page_w - margin, footer_y - 14)
    page.insert_text(
        (margin, footer_y),
        "Costs are estimates from VR-Nexus's own pricing table, not a billing source of truth.",
        fontsize=7.5, fontname="helv", color=_PDF_MUTED,
    )

    doc.save(str(path))
    doc.close()


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
        answer a requirement);
      - api_usage_report.pdf, a one-page visual summary (logo, totals table,
        by-purpose table, bar charts) of this tender's own Anthropic API
        call totals and cost (see compute_tender_usage / _write_usage_report_pdf);
        and
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
        .filter(Requirement.tender_id == tender.id, Requirement.duplicate_of_id.is_(None))
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

    # Extra labels this tender produced, in a stable order, but only the ones
    # that earn a column.
    #
    # This used to be an unconditional union of every key ever seen, and it is
    # why one 125-page tender produced a 92-column sheet: 58 of those columns
    # were filled in exactly ONE row out of 687, because a single arbitration
    # clause was enough to mint a permanent "Appointing Authority for
    # Arbitrator" column. A column that is blank in 99.9% of rows is not data
    # preservation, it is a sheet nobody can read.
    #
    # Extraction no longer emits extra_fields at all (see
    # ExtractedRequirement in app/services/extraction.py), so for any tender
    # analysed from now on this loop finds nothing. The gate stays for the
    # tenders already in the database, which still carry their extras and still
    # have to render.
    #
    # Below the threshold the value is not lost: _requirement_cells folds it
    # into Remarks as "label: value", which costs one cell instead of one
    # column across every row.
    EXTRA_COLUMN_MIN_FILL = 0.10
    fill_counts: dict = {}
    for r in requirements:
        for key, value in (r.extra_fields or {}).items():
            if str(value or "").strip():
                fill_counts[str(key)] = fill_counts.get(str(key), 0) + 1
    row_total = max(len(requirements), 1)
    extra_keys = sorted(
        (k for k, n in fill_counts.items() if n / row_total >= EXTRA_COLUMN_MIN_FILL),
        key=str.lower,
    )
    demoted_extra_keys = {k for k in fill_counts if k not in set(extra_keys)}
    if demoted_extra_keys:
        logger.info(
            "Tender %s: %s extra field(s) folded into Remarks (under %.0f%% fill), %s kept as columns.",
            tender.id, len(demoted_extra_keys), EXTRA_COLUMN_MIN_FILL * 100, len(extra_keys),
        )

    # Responsibility-matrix columns that only apply to some bids, and so are
    # rendered only when this tender actually has values for them.
    #
    # "dpl", "prime" and "the_t" are one specific consortium's partner names
    # (DPL, PRIME, The Tulepaak) that were hardcoded as fields. On a tender
    # where DPL bids alone they are empty in every row, and a 687-row sheet
    # carried three columns that were 100% blank. Extraction no longer writes
    # them at all - it returns an owner hint instead, which lands in
    # "responsibility" - so on new tenders these are always absent, and on the
    # tenders already in the database they appear only if they hold something.
    #
    # Only the default layout prunes. A user who explicitly put a column in
    # their own template asked for it, so a template renders exactly what it
    # says, empty or not.
    # The legacy partner columns only. The derived owner columns are not
    # conditional: blank across every row is itself the signal that nothing was
    # assigned, and a bid manager needs the columns there to fill in.
    CONDITIONAL_FIXED_KEYS = ("dpl", "prime", "the_t", "joint_responsibility")

    def _has_values(key: str) -> bool:
        return any(str(_row_values(r, [])[key] or "").strip() for r in requirements)

    # Excel export customization: an override on this tender, else the
    # uploading user's saved default, else None (the original fixed layout).
    # See _resolve_excel_template / _build_template_columns.
    template = _resolve_excel_template(db, tender)
    columns = _build_template_columns(template, extra_keys) if template else [
        {"key": key, "label": FIXED_COLUMN_REGISTRY[key]["label"], "wrap": FIXED_COLUMN_REGISTRY[key]["wrap"], "width": FIXED_COLUMN_REGISTRY[key]["width"], "is_extra": False}
        for key in FIXED_COLUMN_KEYS
        if key not in CONDITIONAL_FIXED_KEYS or _has_values(key)
    ] + [
        {"key": key, "label": key, "wrap": False, "width": 22, "is_extra": True} for key in extra_keys
    ]
    added_columns = list(template.added_columns) if template else []
    delete_empty_rows = bool(template.delete_empty_rows) if template else False

    main_headers = [c["label"] for c in columns] + added_columns
    ws.append(main_headers)

    wrap_column_indexes = {i for i, c in enumerate(columns, start=1) if c["wrap"]}
    data_rows_written = 0

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

        values = _row_values(r, files, demoted_extra_keys)
        extras = r.extra_fields or {}

        row_cells = []
        for c in columns:
            if c["is_extra"]:
                row_cells.append(extras.get(c["key"], ""))
            else:
                row_cells.append(values.get(c["key"], ""))
        row_cells.extend([""] * len(added_columns))  # user-added columns: blank, filled in manually

        if delete_empty_rows and not any(
            (cell is not None and str(cell).strip()) for cell in row_cells
        ):
            continue

        ws.append(row_cells)
        data_rows_written += 1

    _style_header(ws, len(main_headers))
    _set_widths(ws, [c["width"] for c in columns] + [22] * len(added_columns))
    # The prose columns wrap (per-column, from the registry/template); everything
    # else stays on one line so the sheet scans.
    for row in ws.iter_rows(min_row=2):
        for index in wrap_column_indexes:
            if index <= len(row):
                row[index - 1].alignment = _WRAP_TOP

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
    if tender.extraction_warnings:
        # Task: failed-chunk visibility. Surfaced here, not buried in a worker
        # log, because this is the sheet a reviewer actually opens - a thin
        # tracker with no explanation reads as "the tool missed things" even
        # when the document genuinely has few requirements. This row makes the
        # distinction visible: which pages, if any, could not be read.
        ws2.append(["⚠ Extraction warning", tender.extraction_warnings])
        warning_row = ws2.max_row
        ws2.cell(row=warning_row, column=1).font = _WARNING_FONT
        ws2.cell(row=warning_row, column=2).font = _WARNING_FONT
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

    # Reconcile the summed marks against what the tender says is on offer.
    #
    # These two numbers come from independent places - "Marks available" is the
    # sum of what extraction found per requirement, "stated" is the figure the
    # tender's own evaluation section quotes - so when they disagree, the sum is
    # wrong and every percentage derived from it is wrong with it. One shipped
    # tracker read "Marks available: 222" for a 100-mark tender, because its
    # scoring table appears twice and the experience bands were added together
    # as though one expert could score all three. Nothing in that workbook said
    # so; the number simply looked authoritative.
    #
    # A flagged disagreement is strictly better than a confident wrong total, so
    # this warns in place rather than silently correcting to the stated figure:
    # the sum being too HIGH means double-counting, too LOW means marks were
    # missed, and those need opposite fixes.
    stated = float(tender.stated_technical_marks) if tender.stated_technical_marks is not None else None
    if stated and marks_available > 0 and abs(marks_available - stated) >= 0.5:
        direction = "double-counted" if marks_available > stated else "incomplete"
        ws2.append([
            "⚠ Marks check",
            f"Extracted {round(marks_available, 2):g} against the {stated:g} this tender states. "
            f"The per-requirement marks look {direction}, so treat Coverage % as indicative "
            f"until the scoring rows are reviewed.",
        ])
        check_row = ws2.max_row
        ws2.cell(row=check_row, column=1).font = _WARNING_FONT
        ws2.cell(row=check_row, column=2).font = _WARNING_FONT
        logger.warning(
            "Tender %s marks reconciliation: extracted %.2f vs stated %.2f (%s).",
            tender.id, marks_available, stated, direction,
        )
    elif stated:
        ws2.append(["Marks check", f"Matches the {stated:g} technical marks this tender states."])
    if tender.passing_technical_score is not None:
        ws2.append(["Passing technical score", float(tender.passing_technical_score)])

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

    # --- Sheet 3b: Excluded sections (only when triage actually skipped) --- #
    #
    # The audit surface for Stage A page triage. Extraction now skips the page
    # spans judged to be post-award contract terms or front matter, which is
    # nearly half of some tenders, and a tracker that silently covered only
    # 58% of a document would be worse than the noisy one it replaced. This
    # sheet says which pages were skipped and why, so a reviewer can disagree
    # rather than having to take the row count on trust.
    #
    # Omitted entirely when nothing was excluded, rather than added as an empty
    # sheet: a sheet that is always present and usually blank stops being read.
    triage = load_triage_outcome(tender.section_triage)
    excluded_spans = [s for s in triage.spans if s.kind not in TRIAGE_EXTRACTED_KINDS]
    if triage.applied and excluded_spans:
        ws_ex = wb.create_sheet("Excluded sections")
        ws_ex.append(["Pages", "Section", "Why it was skipped"])
        why = {
            "POST_AWARD": "Post-award contract terms: binding only after award, so no bid action.",
            "NON_SUBSTANTIVE": "Front matter: contents, indexes, definitions or background.",
        }
        for span in excluded_spans:
            pages_label = (
                str(span.page_start) if span.page_start == span.page_end
                else f"{span.page_start}-{span.page_end}"
            )
            ws_ex.append([pages_label, span.label or "", why.get(span.kind, span.kind)])
        _style_header(ws_ex, 3)
        _set_widths(ws_ex, [12, 40, 60])
        ws_ex.append([])
        ws_ex.append(["", "", triage.reason])
        ws_ex.append([
            "", "",
            "Every page was still read and chunked; these spans were not sent for "
            "requirement extraction. If a requirement is missing from the Requirements "
            "sheet and you believe it lives in one of these spans, re-run the analysis "
            "and flag it, because that is a triage error worth fixing.",
        ])

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
        "api_usage_report.pdf",
        "  What this tender's own VR-Nexus analysis cost in Anthropic API calls - a table",
        "  and bar charts of calls, tokens and estimated cost, broken down by purpose. For",
        "  tracking spend, not part of the tender submission itself.",
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

    # --- this tender's own API usage/cost, for whoever opens the ZIP ------- #
    try:
        _write_usage_report_pdf(folder / "api_usage_report.pdf", tender, compute_tender_usage(db, tender.id))
    except Exception:
        # Never let a usage-reporting hiccup block the requirements tracker,
        # evidence files and summary.json the reviewer actually needs.
        logger.exception("Could not write api_usage_report.pdf for tender %s", tender.id)

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
        "extraction_warnings": tender.extraction_warnings,
        "evidence_matches_total": match_total,
        "evidence_files_included": len(doc_relpath),
        "missing_evidence_files": missing_files,
        "marks_available": (
            float(tender.total_marks_available) if tender.total_marks_available is not None else None
        ),
        "marks_captured": (
            float(tender.total_marks_captured) if tender.total_marks_captured is not None else None
        ),
        # The tender's own stated totals, so a consumer of summary.json can run
        # the same check the Summary sheet shows rather than trusting
        # marks_available on its own - see _marks_reconciliation above.
        "stated_technical_marks": (
            float(tender.stated_technical_marks) if tender.stated_technical_marks is not None else None
        ),
        "passing_technical_score": (
            float(tender.passing_technical_score) if tender.passing_technical_score is not None else None
        ),
        "marks_reconciled": (
            None if (tender.stated_technical_marks is None or not marks_available)
            else abs(marks_available - float(tender.stated_technical_marks)) < 0.5
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
