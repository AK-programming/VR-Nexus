"""
Tender endpoints — upload + the Stage 2-4 read/review surface.

Upload is now a thin front door: it validates, stores the PDF, creates the
Tender(UPLOADED) row, and hands everything else to the Celery pipeline
(app.tasks.tender_pipeline), exactly like the Evidence Library's
upload → train → index split. The heavy parse → chunk → extract → match →
report → assemble sequence used to run inline in the request (and again in a
second, near-duplicate endpoint in routes/tender.py, now deleted); it all runs
in the worker now, so the request returns in milliseconds and the client
follows the progress WebSocket at /ws/tenders/{id}/progress.

Everything after upload is a read or a review action against what the pipeline
produced: list / detail, requirements, evidence matches, a computed report, the
source PDF, the assembled output zip, per-match accept/reject/reassign, and
finalize.
"""
from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.models.document import Document
from app.models.enums import (
    EvaluationImpact,
    MatchReviewStatus,
    MatchType,
    TenderStatus,
)
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.models.user import User
from app.schemas.tender import (
    EvidenceMatchOut,
    ImpactBreakdown,
    MatchReviewUpdate,
    RequirementOut,
    TenderListItem,
    TenderOut,
    TenderReportOut,
    TenderUpdate,
    TenderUploadResponse,
    WsTicketOut,
)
from app.services.progress import publish_progress
from app.services.tender_storage import save_tender_file, validate_tender_upload
from app.services.ws_tickets import issue_ticket
from app.celery_app import celery_app
from app.tasks.tender_pipeline import enqueue as enqueue_pipeline, rebuild_outputs

logger = logging.getLogger(__name__)

_settings = get_settings()

router = APIRouter(prefix="/api/tenders", tags=["tenders"])

# Highest-quality match a requirement has, for the requirements-table summary.
_MATCH_TYPE_RANK = {MatchType.AUTO: 3, MatchType.SUGGESTED: 2, MatchType.MISSING: 1}


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _get_tender(db: Session, tender_id: uuid.UUID) -> Tender:
    """Fetch a tender by id - deliberately with no owner/uploader check.

    Every tender in this app is visible and actionable by every signed-in
    user, on purpose: this is a shared workspace for one internal sales team,
    not a multi-tenant product, and `uploaded_by` exists for attribution (who
    brought this tender in), not access control. If VR-Nexus ever needs to
    scope tenders to their uploader, this is the one place to add that check -
    every route below calls through here.
    """
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tender not found.")
    return tender


def _tender_out(tender: Tender) -> TenderOut:
    out = TenderOut.model_validate(tender)
    # has_output is derived, never stored — we don't expose the raw server path.
    out.has_output = bool(tender.output_zip_path and Path(tender.output_zip_path).is_file())
    return out


def _best_match_type(matches) -> MatchType | None:
    if not matches:
        return None
    return max((m.match_type for m in matches), key=lambda t: _MATCH_TYPE_RANK.get(t, 0))


def _requirement_covered(matches) -> bool:
    """A requirement counts as covered when it has an ACCEPTED match, or an AUTO
    match that hasn't been rejected. Matches the pipeline's REPORTING rule
    (tasks/tender_pipeline._compute_report) so the on-demand report and the
    persisted totals agree."""
    return any(
        m.review_status == MatchReviewStatus.ACCEPTED
        or (m.match_type == MatchType.AUTO and m.review_status != MatchReviewStatus.REJECTED)
        for m in matches
    )


def _match_out(m: RequirementEvidenceMatch) -> EvidenceMatchOut:
    doc = m.document
    req = m.requirement
    return EvidenceMatchOut(
        id=m.id,
        requirement_id=m.requirement_id,
        requirement_clause=req.clause_reference if req else None,
        requirement_description=req.description if req else "",
        document_id=m.document_id,
        document_title=(doc.title or None) if doc else None,
        document_filename=doc.original_filename if doc else None,
        document_category=doc.category.value if doc and doc.category else None,
        confidence_score=float(m.confidence_score) if m.confidence_score is not None else None,
        match_type=m.match_type,
        review_status=m.review_status,
        reviewed_at=m.reviewed_at,
        created_at=m.created_at,
    )


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "tender").strip()) or "tender"
    return base[:100]


# --------------------------------------------------------------------------- #
# upload (Stage 1 → enqueue Stage 2-4)                                        #
# --------------------------------------------------------------------------- #
@router.post("", response_model=TenderUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_tender(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderUploadResponse:
    """Validate + store the PDF, create the Tender row, enqueue the pipeline.

    Returns 201 immediately; the analysis runs in the Celery worker and reports
    over the progress WebSocket.
    """
    content = await file.read()
    validate_tender_upload(file, content)  # raises HTTPException on .pdf / size / empty

    filename = file.filename or "tender.pdf"

    tender = Tender(
        name=filename,
        original_filename=filename,
        file_path="",  # set right below, once we have an id for the storage path
        file_size_bytes=len(content),
        status=TenderStatus.UPLOADED,
        progress_percent=0,
        uploaded_by=current_user.id,
    )
    db.add(tender)
    db.commit()
    db.refresh(tender)

    tender.file_path = save_tender_file(tender.id, filename, content)
    db.commit()

    publish_progress(
        str(tender.id), TenderStatus.UPLOADED,
        message="File received and queued for analysis.",
    )
    enqueue_pipeline(tender.id, tender.run_generation)

    return TenderUploadResponse.model_validate(tender)


# --------------------------------------------------------------------------- #
# list + detail                                                               #
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[TenderListItem])
def list_tenders(
    tender_status: TenderStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TenderListItem]:
    stmt = select(Tender).order_by(Tender.created_at.desc())
    if tender_status is not None:
        stmt = stmt.where(Tender.status == tender_status)
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars()
    return [TenderListItem.model_validate(r) for r in rows]


@router.get("/{tender_id}", response_model=TenderOut)
def get_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    return _tender_out(_get_tender(db, tender_id))


@router.post("/{tender_id}/ws-ticket", response_model=WsTicketOut)
def create_tender_ws_ticket(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WsTicketOut:
    """Mint a one-shot ticket for /ws/tenders/{tender_id}/progress.

    Called over a normal authenticated fetch() right before opening the
    socket, so the real access token never has to leave this response and
    land in a WebSocket URL (browser history, proxy logs, Referer). See
    app/services/ws_tickets.py for the full rationale.
    """
    _get_tender(db, tender_id)  # 404s on a bad id before we bother minting anything
    ticket = issue_ticket(current_user.id, "tender", str(tender_id))
    return WsTicketOut(ticket=ticket)


@router.patch("/{tender_id}", response_model=TenderOut)
def update_tender(
    tender_id: uuid.UUID,
    payload: TenderUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    """Edit tender metadata (the fields the LLM fills best-effort, plus name and
    evaluation weighting). Only the fields present in the body are changed."""
    tender = _get_tender(db, tender_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and not (updates["name"] or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Name cannot be empty.")
    for field, value in updates.items():
        setattr(tender, field, value)
    db.commit()
    db.refresh(tender)
    return _tender_out(tender)


# --------------------------------------------------------------------------- #
# requirements                                                                #
# --------------------------------------------------------------------------- #
@router.get("/{tender_id}/requirements", response_model=list[RequirementOut])
def list_requirements(
    tender_id: uuid.UUID,
    is_mandatory: bool | None = Query(None),
    evaluation_impact: EvaluationImpact | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RequirementOut]:
    _get_tender(db, tender_id)
    stmt = (
        select(Requirement)
        .where(Requirement.tender_id == tender_id)
        .options(selectinload(Requirement.evidence_matches))
        .order_by(Requirement.page_number, Requirement.created_at)
    )
    if is_mandatory is not None:
        stmt = stmt.where(Requirement.is_mandatory == is_mandatory)
    if evaluation_impact is not None:
        stmt = stmt.where(Requirement.evaluation_impact == evaluation_impact)

    result: list[RequirementOut] = []
    for r in db.execute(stmt).scalars():
        item = RequirementOut.model_validate(r)
        item.match_count = len(r.evidence_matches)
        item.best_match_type = _best_match_type(r.evidence_matches)
        result.append(item)
    return result


# --------------------------------------------------------------------------- #
# evidence matches + review                                                   #
# --------------------------------------------------------------------------- #
@router.get("/{tender_id}/matches", response_model=list[EvidenceMatchOut])
def list_matches(
    tender_id: uuid.UUID,
    match_type: MatchType | None = Query(None),
    review_status: MatchReviewStatus | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[EvidenceMatchOut]:
    _get_tender(db, tender_id)
    stmt = (
        select(RequirementEvidenceMatch)
        .join(Requirement, RequirementEvidenceMatch.requirement_id == Requirement.id)
        .where(Requirement.tender_id == tender_id)
        .options(
            selectinload(RequirementEvidenceMatch.requirement),
            selectinload(RequirementEvidenceMatch.document),
        )
        .order_by(RequirementEvidenceMatch.confidence_score.desc())
    )
    if match_type is not None:
        stmt = stmt.where(RequirementEvidenceMatch.match_type == match_type)
    if review_status is not None:
        stmt = stmt.where(RequirementEvidenceMatch.review_status == review_status)
    return [_match_out(m) for m in db.execute(stmt).scalars()]


@router.patch("/{tender_id}/matches/{match_id}", response_model=EvidenceMatchOut)
def review_match(
    tender_id: uuid.UUID,
    match_id: uuid.UUID,
    payload: MatchReviewUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EvidenceMatchOut:
    """Accept / reject / reassign one evidence match (TN-MTC-05)."""
    _get_tender(db, tender_id)
    match = db.get(RequirementEvidenceMatch, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Match not found.")
    # Guard that the match actually belongs to this tender.
    requirement = db.get(Requirement, match.requirement_id)
    if requirement is None or requirement.tender_id != tender_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Match not found for this tender.")

    if payload.action == "accept":
        match.review_status = MatchReviewStatus.ACCEPTED
    elif payload.action == "reject":
        match.review_status = MatchReviewStatus.REJECTED
    else:  # reassign
        if payload.document_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "document_id is required to reassign a match.",
            )
        if db.get(Document, payload.document_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Target document not found.")
        match.document_id = payload.document_id
        match.review_status = MatchReviewStatus.REASSIGNED

    match.reviewed_by = current_user.id
    match.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    # Reload with relationships for the response.
    match = db.execute(
        select(RequirementEvidenceMatch)
        .where(RequirementEvidenceMatch.id == match_id)
        .options(
            selectinload(RequirementEvidenceMatch.requirement),
            selectinload(RequirementEvidenceMatch.document),
        )
    ).scalars().first()
    return _match_out(match)


# --------------------------------------------------------------------------- #
# report                                                                      #
# --------------------------------------------------------------------------- #
@router.get("/{tender_id}/report", response_model=TenderReportOut)
def get_report(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderReportOut:
    """Computed report: marks available vs. captured, coverage, mandatory split,
    a per-evaluation-impact breakdown, and match-review tallies. Computed live
    from the current requirement + match state, never persisted."""
    tender = _get_tender(db, tender_id)
    requirements = db.execute(
        select(Requirement)
        .where(Requirement.tender_id == tender_id)
        .options(selectinload(Requirement.evidence_matches))
    ).scalars().all()

    mandatory = optional = unspecified = 0
    with_evidence = without_evidence = not_required = 0
    auto = suggested = missing = accepted = rejected = pending = 0
    marks_available = marks_captured = 0.0
    impact_agg: dict[str, dict] = {}

    for r in requirements:
        if r.is_mandatory is True:
            mandatory += 1
        elif r.is_mandatory is False:
            optional += 1
        else:
            unspecified += 1

        # requirements_with_evidence/without_evidence describe requirements the
        # tender actually asks the bidder to prove. A requirement with
        # evidence_required=False was never going to carry evidence — counting
        # it under "without evidence" would just relabel a normal row as
        # Unmatched. It gets its own bucket instead.
        if not r.evidence_required:
            not_required += 1
        elif r.evidence_matches:
            with_evidence += 1
        else:
            without_evidence += 1

        covered = _requirement_covered(r.evidence_matches)
        r_marks = float(r.marks) if r.marks is not None else 0.0
        marks_available += r_marks
        if covered:
            marks_captured += r_marks

        impact_key = r.evaluation_impact.value if r.evaluation_impact else "unspecified"
        agg = impact_agg.setdefault(impact_key, {"count": 0, "available": 0.0, "captured": 0.0})
        agg["count"] += 1
        agg["available"] += r_marks
        if covered:
            agg["captured"] += r_marks

        for m in r.evidence_matches:
            if m.match_type == MatchType.AUTO:
                auto += 1
            elif m.match_type == MatchType.SUGGESTED:
                suggested += 1
            elif m.match_type == MatchType.MISSING:
                missing += 1
            if m.review_status == MatchReviewStatus.ACCEPTED:
                accepted += 1
            elif m.review_status == MatchReviewStatus.REJECTED:
                rejected += 1
            elif m.review_status == MatchReviewStatus.PENDING:
                pending += 1

    coverage = (marks_captured / marks_available * 100.0) if marks_available > 0 else 0.0
    by_impact = [
        ImpactBreakdown(
            impact=key,
            requirement_count=v["count"],
            marks_available=round(v["available"], 2),
            marks_captured=round(v["captured"], 2),
        )
        for key, v in sorted(impact_agg.items())
    ]

    return TenderReportOut(
        tender_id=tender.id,
        requirements_total=len(requirements),
        mandatory_count=mandatory,
        optional_count=optional,
        unspecified_count=unspecified,
        marks_available=round(marks_available, 2),
        marks_captured=round(marks_captured, 2),
        coverage_percent=round(coverage, 1),
        auto_matches=auto,
        suggested_matches=suggested,
        missing_matches=missing,
        accepted_matches=accepted,
        rejected_matches=rejected,
        pending_matches=pending,
        requirements_with_evidence=with_evidence,
        requirements_without_evidence=without_evidence,
        requirements_not_required=not_required,
        by_evaluation_impact=by_impact,
        evaluation_weighting=tender.evaluation_weighting,
    )


# --------------------------------------------------------------------------- #
# files                                                                       #
# --------------------------------------------------------------------------- #
@router.get("/{tender_id}/file")
def get_tender_file(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Serve the source PDF inline for the in-browser viewer.

    Authenticated like every other route; the client fetches with its bearer
    token and hands the viewer a blob URL (an <iframe src> straight at this path
    would arrive without the Authorization header and 401). Mirrors the library
    file-serve.
    """
    tender = _get_tender(db, tender_id)
    if not tender.file_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No source file recorded for this tender.")

    resolved = Path(tender.file_path).resolve()
    storage_root = Path(_settings.TENDER_STORAGE_DIR).resolve()
    if not resolved.is_relative_to(storage_root):
        logger.warning("Refusing to serve %s: outside the tender storage root", resolved)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is outside the storage root.")
    if not resolved.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The stored file is missing.")

    return FileResponse(
        resolved,
        filename=tender.original_filename,
        media_type="application/pdf",
        content_disposition_type="inline",
    )


@router.get("/{tender_id}/download")
def download_output(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Stream the assembled output zip (TN-OUT-04)."""
    tender = _get_tender(db, tender_id)
    if not tender.output_zip_path:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The output folder has not been assembled yet."
        )

    resolved = Path(tender.output_zip_path).resolve()
    output_root = Path(_settings.OUTPUT_STORAGE_DIR).resolve()
    if not resolved.is_relative_to(output_root):
        logger.warning("Refusing to serve %s: outside the output storage root", resolved)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is outside the storage root.")
    if not resolved.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The output archive is missing.")

    return FileResponse(
        resolved,
        filename=f"{_safe_filename(tender.name)}-analysis.zip",
        media_type="application/zip",
    )


# --------------------------------------------------------------------------- #
# finalize                                                                    #
# --------------------------------------------------------------------------- #
@router.post("/{tender_id}/finalize", response_model=TenderOut)
def finalize_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    """Lock in the reviewed analysis (TN-OUT-05).

    Re-runs the report + output assembly against the current (human-reviewed)
    match state, stamps finalized_at, and publishes FINALIZED — which is
    terminal for the progress socket, so a watching client's connection closes.
    Allowed only once the pipeline has reached READY_FOR_REVIEW (re-finalizing
    an already-finalized tender is permitted and simply rebuilds the output).
    """
    tender = _get_tender(db, tender_id)
    if tender.status not in (TenderStatus.READY_FOR_REVIEW, TenderStatus.FINALIZED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This tender is not ready to finalize yet.",
        )

    rebuild_outputs(db, tender)  # recompute marks + reassemble folder/zip from reviewed matches

    tender.finalized_at = datetime.now(timezone.utc)
    tender.status = TenderStatus.FINALIZED
    tender.progress_percent = 100
    tender.progress_message = "Finalized."
    db.commit()
    db.refresh(tender)

    publish_progress(
        str(tender.id), TenderStatus.FINALIZED,
        percent=100, message="Tender finalized.",
    )
    return _tender_out(tender)


# --------------------------------------------------------------------------- #
# cancel (stop a running analysis)                                            #
# --------------------------------------------------------------------------- #
@router.post("/{tender_id}/cancel", response_model=TenderOut)
def cancel_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    """Stop a tender that is still being analysed.

    Marks the tender FAILED with a "Stopped by user." message and publishes that
    over the progress socket (terminal, so a watching client stops immediately).

    Two layers, not one. `run_generation` is bumped first: every write the
    worker makes back onto this row (tasks/tender_pipeline._advance / _fail) is
    conditioned on that value, so as of this commit the running worker's next
    check-in is rejected outright, no matter how long it takes to notice. On
    top of that, if we know which Celery task owns the row, we send it a hard
    revoke - best-effort, since terminate depends on the worker pool actually
    supporting it, which is exactly why the generation bump above is the real
    guarantee and this is only how the stop happens sooner rather than only
    correctly. Only allowed while the tender is still in flight — a tender at
    ready_for_review, finalized or already failed has nothing to stop.
    """
    tender = _get_tender(db, tender_id)
    settled = (
        TenderStatus.READY_FOR_REVIEW,
        TenderStatus.FINALIZED,
        TenderStatus.FAILED,
    )
    if tender.status in settled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This tender is not running, so there is nothing to stop.",
        )

    # Read the stage BEFORE overwriting it — this is the one thing a person asking
    # "how far did it get?" wants, and assigning FAILED first would record "failed"
    # as the stage it was stopped at, which says nothing.
    stopped_at = tender.status.value
    task_id = tender.celery_task_id

    tender.run_generation += 1
    tender.status = TenderStatus.FAILED
    tender.progress_message = "Stopped by user."
    # Recorded like any other failure so the Processing page's error log shows the
    # stop alongside real failures. The detail says it was a deliberate stop rather
    # than leaving a blank that reads like a crash.
    tender.failed_stage = stopped_at
    tender.error_detail = "Stopped by user from the Processing page."
    tender.failed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tender)

    if task_id:
        celery_app.control.revoke(task_id, terminate=True)

    publish_progress(
        str(tender.id), TenderStatus.FAILED,
        percent=tender.progress_percent, message="Stopped by user.",
    )
    return _tender_out(tender)


# --------------------------------------------------------------------------- #
# reprocess (retry a failed / stopped analysis)                               #
# --------------------------------------------------------------------------- #
@router.post("/{tender_id}/reprocess", response_model=TenderOut)
def reprocess_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    """Run the analysis pipeline again for a tender that failed or was stopped.

    Safe to call repeatedly: every stage of the pipeline deletes its own prior
    rows for this tender before writing (chunks, requirements, matches), so a
    re-run replaces the previous attempt rather than duplicating it. The row is
    reset to UPLOADED first so the progress socket and the Processing queue both
    treat it as a fresh run.

    Bumping `run_generation` here is what actually keeps two workers off the
    same tender, not just the 409 below. The 409 only blocks a *second click*
    while the row still reads as running; it does nothing about a worker that
    was told to stop (via Cancel, which bumped the generation once already) but
    hasn't actually noticed yet. Reprocess can be called the instant the row
    reads FAILED, which is immediately - so bumping the generation again here
    guarantees that stale worker's next write is rejected too, even though a
    brand new task for this fresh attempt is about to start racing it.
    """
    tender = _get_tender(db, tender_id)
    if tender.status not in (
        TenderStatus.FAILED,
        TenderStatus.READY_FOR_REVIEW,
        TenderStatus.FINALIZED,
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This tender is still being analysed. Stop it before retrying.",
        )

    tender.run_generation += 1
    tender.celery_task_id = None
    tender.status = TenderStatus.UPLOADED
    tender.progress_percent = 0
    tender.progress_message = "Queued for re-analysis."
    tender.finalized_at = None
    # The failure record describes the attempt that just ended, so it is cleared
    # here rather than left to be read as the state of the run about to start.
    tender.failed_stage = None
    tender.error_detail = None
    tender.failed_at = None
    tender.support_requested_at = None
    db.commit()
    db.refresh(tender)

    publish_progress(
        str(tender.id), TenderStatus.UPLOADED,
        percent=0, message="Queued for re-analysis.",
    )
    enqueue_pipeline(tender.id, tender.run_generation)
    return _tender_out(tender)


# --------------------------------------------------------------------------- #
# delete (remove a tender entirely)                                           #
# --------------------------------------------------------------------------- #
@router.delete("/{tender_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_tender(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a tender and everything on disk that belongs to it.

    Removes the row (which cascades to `tender_chunks`, `requirements` and
    `requirement_evidence_matches`), the source PDF, the assembled output folder
    and the output zip. Deliberately allowed at any status — including while a
    run is in flight — because a stuck or unwanted run is exactly the case a
    Delete button is offered for. A worker still processing the tender will hit
    a missing row on its next `db.refresh` and stop.

    Files are best-effort: an on-disk cleanup failure is logged but does not
    fail the delete, because the database is the source of truth and a stray
    file with no row is a clean-up chore rather than corruption. The row goes
    first so a mid-delete crash leaves nothing pointing at half-deleted files.
    """
    tender = _get_tender(db, tender_id)

    source_path = tender.file_path
    folder_path = tender.output_folder_path
    zip_path = tender.output_zip_path

    db.delete(tender)
    db.commit()

    # Best-effort file cleanup. Each try isolated so a failure on one artefact
    # does not skip the others.
    for path_str in (source_path, zip_path):
        if not path_str:
            continue
        try:
            path = Path(path_str)
            if path.is_file():
                path.unlink()
        except OSError:
            logger.exception("Failed to remove tender file at %s", path_str)

    if folder_path:
        try:
            folder = Path(folder_path)
            if folder.is_dir():
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            logger.exception("Failed to remove tender output folder at %s", folder_path)


# --------------------------------------------------------------------------- #
# report-issue (email a failure to the technical support team)                #
# --------------------------------------------------------------------------- #
@router.post("/{tender_id}/report-issue", response_model=TenderOut)
def report_tender_issue(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenderOut:
    """Record that a user has handed a failed tender to the support team.

    The email itself is composed and sent from the user's OWN mailbox: the
    frontend opens a pre-filled Gmail compose window (support address + the full
    error) when the button is pressed, and the user sends it. This endpoint only
    persists that the hand-off happened, which is what flips the error log entry
    from the technical error to the calm "we're on it, please wait" state and
    keeps it that way across reloads.

    Sending from the user's own mailbox rather than a server SMTP account means
    no mail credentials to configure, no new-sender spam problems, and the
    support team gets a message from a real person they can reply to directly.

    Only valid for a tender that actually failed — there is nothing to report on
    a run that is still going or that finished.
    """
    tender = _get_tender(db, tender_id)

    if tender.status != TenderStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This tender has not failed, so there is nothing to report.",
        )

    tender.support_requested_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tender)
    return _tender_out(tender)
