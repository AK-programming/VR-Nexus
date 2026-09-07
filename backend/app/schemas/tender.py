"""
Request/response shapes for the tender endpoints (Tasks 2.1/2.2 ingestion, plus
the Stage 2-4 read/review endpoints in routes/tenders.py).

Money and marks are typed as float rather than Decimal on purpose: the columns
are Numeric, but Pydantic serialises Decimal to a JSON *string* in json mode,
which the frontend would then have to parse back to a number everywhere. float
keeps the wire values as JSON numbers; the DB column stays the source of truth
for precision.
"""
import uuid
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.enums import (
    EvaluationImpact,
    MatchReviewStatus,
    MatchType,
    RequirementStatus,
    TenderStatus,
)


class WsTicketOut(BaseModel):
    """A short-lived, single-use ticket for the tender progress WebSocket.

    Minted over this ordinary authenticated HTTP call and handed to the
    socket as `?ticket=` instead of the real access token - see
    app/services/ws_tickets.py for why.
    """

    ticket: str


class TenderChunkOut(BaseModel):
    chunk_index: int
    section: str
    page_start: int
    page_end: int
    token_count: int
    overlap_tokens: int

    model_config = {"from_attributes": True}


class TenderUploadResponse(BaseModel):
    """Returned immediately from POST /api/tenders.

    The heavy pipeline (parse → chunk → extract → match → report → assemble)
    runs in a Celery worker now, so page_count and chunk/section counts are not
    known at upload time — the client follows the progress WebSocket (or polls
    GET /{id}) for everything after UPLOADED.
    """
    id: uuid.UUID
    name: str
    original_filename: str
    status: TenderStatus
    progress_percent: int
    page_count: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TenderListItem(BaseModel):
    """One row in GET /api/tenders."""
    id: uuid.UUID
    name: str
    original_filename: str
    status: TenderStatus
    progress_percent: int
    extracted_requirements_count: int
    page_count: Optional[int] = None
    issuing_authority: Optional[str] = None
    submission_deadline: Optional[date] = None
    finalized_at: Optional[datetime] = None
    created_at: datetime

    # Carried on the list row, not just the detail, because the error log on the
    # Processing page is built from the one list read that page already makes —
    # fetching a detail per failed tender to show a sentence would be a request
    # per row for data the list could have carried.
    progress_message: Optional[str] = None

    # --- failure record (the Processing page's error log) ---
    # `progress_message` is the one-line reason; the three below say where it
    # died, the exception + stack tail, and when. All null on a tender that has
    # not failed, and cleared again when it is reprocessed.
    failed_stage: Optional[str] = None
    error_detail: Optional[str] = None
    failed_at: Optional[datetime] = None
    # Set once the failure was emailed to support; flips the UI to "reported".
    support_requested_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TenderOut(BaseModel):
    """Full detail for GET /api/tenders/{id}."""
    id: uuid.UUID
    name: str
    original_filename: str
    page_count: Optional[int] = None
    file_size_bytes: Optional[int] = None
    status: TenderStatus
    progress_percent: int
    progress_message: Optional[str] = None
    extracted_requirements_count: int

    reference_id: Optional[str] = None
    issuing_authority: Optional[str] = None
    sector: Optional[str] = None
    location: Optional[str] = None
    tender_value: Optional[float] = None
    submission_deadline: Optional[date] = None

    evaluation_weighting: Optional[dict] = None
    total_marks_available: Optional[float] = None
    total_marks_captured: Optional[float] = None

    # Whether Stage 4 has produced a downloadable output zip (GET /{id}/download).
    # Set by the route, not stored — we never expose the raw server path.
    has_output: bool = False
    finalized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    # --- failure record (the Processing page's error log) ---
    # `progress_message` is the one-line reason; the three below say where it
    # died, the exception + stack tail, and when. All null on a tender that has
    # not failed, and cleared again when it is reprocessed.
    failed_stage: Optional[str] = None
    error_detail: Optional[str] = None
    failed_at: Optional[datetime] = None
    # Set once the failure was emailed to support; flips the UI to "reported".
    support_requested_at: Optional[datetime] = None


    model_config = {"from_attributes": True}


class TenderUpdate(BaseModel):
    """PATCH /api/tenders/{id} — every field optional; only those sent are applied."""
    name: Optional[str] = None
    reference_id: Optional[str] = None
    issuing_authority: Optional[str] = None
    sector: Optional[str] = None
    location: Optional[str] = None
    tender_value: Optional[float] = None
    submission_deadline: Optional[date] = None
    evaluation_weighting: Optional[dict] = None


class RequirementOut(BaseModel):
    id: uuid.UUID
    tender_id: uuid.UUID
    page_number: Optional[int] = None
    # The tender's own wording, kept beside the normalised columns: "1-2" pages,
    # "No/Advisory" flags and compound impacts like "Financial / Pass-Fail" are
    # what the tracker has to reproduce, and the enums above cannot hold them.
    page_label: Optional[str] = None
    section_name: Optional[str] = None
    clause_reference: Optional[str] = None
    description: str
    is_mandatory: Optional[bool] = None
    mandatory_raw: Optional[str] = None
    evaluation_impact: Optional[EvaluationImpact] = None
    evaluation_impact_raw: Optional[str] = None
    marks: Optional[float] = None
    evidence_required: bool
    evidence_description: Optional[str] = None
    responsibility: Optional[str] = None
    # Per-member responsibility split, as the client's tracker records it.
    dpl: Optional[str] = None
    prime: Optional[str] = None
    the_t: Optional[str] = None
    joint_responsibility: Optional[str] = None
    # Anything this tender carried that the fixed columns do not model.
    extra_fields: Optional[dict] = None
    status: RequirementStatus
    needs_manual_review: bool
    remarks: Optional[str] = None

    # Coverage summary, filled in by the route from the requirement's matches.
    match_count: int = 0
    best_match_type: Optional[MatchType] = None

    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceMatchOut(BaseModel):
    """One evidence match, flattened with the bits of its document and its
    requirement the review UI needs (built explicitly in the route, since these
    span three tables)."""
    id: uuid.UUID
    requirement_id: uuid.UUID
    requirement_clause: Optional[str] = None
    requirement_description: str
    document_id: uuid.UUID
    document_title: Optional[str] = None
    document_filename: Optional[str] = None
    document_category: Optional[str] = None
    confidence_score: Optional[float] = None
    match_type: MatchType
    review_status: MatchReviewStatus
    reviewed_at: Optional[datetime] = None
    created_at: datetime


class MatchReviewUpdate(BaseModel):
    """PATCH /api/tenders/{id}/matches/{match_id}.

    reassign moves the match to a different library document, so document_id is
    required for that action and ignored for the others.
    """
    action: Literal["accept", "reject", "reassign"]
    document_id: Optional[uuid.UUID] = None


class ImpactBreakdown(BaseModel):
    impact: str
    requirement_count: int
    marks_available: float
    marks_captured: float


class TenderReportOut(BaseModel):
    """GET /api/tenders/{id}/report — computed on demand, never persisted."""
    tender_id: uuid.UUID
    requirements_total: int
    mandatory_count: int
    optional_count: int
    unspecified_count: int

    marks_available: float
    marks_captured: float
    coverage_percent: float

    auto_matches: int
    suggested_matches: int
    missing_matches: int
    accepted_matches: int
    rejected_matches: int
    pending_matches: int

    # Both computed only over evidence_required=True rows: a narrative clause
    # the tender never asked the bidder to prove was never going to have
    # evidence, so counting it here would just mislabel normal rows as
    # "Unmatched" once matching stopped wasting a search on them.
    requirements_with_evidence: int
    requirements_without_evidence: int
    #: evidence_required is False — background/context clauses, not compliance
    #: obligations. Not part of requirements_with_evidence/without_evidence.
    requirements_not_required: int

    by_evaluation_impact: list[ImpactBreakdown]
    evaluation_weighting: Optional[dict] = None
