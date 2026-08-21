"""
Task 4.2 - Match Attachment & Review
Linked requirements: TN-MTC-04, TN-MTC-05

TN-MTC-04 (attaching matched file paths to a requirement row) happens in
app.services.matching when Stage 3 runs during tender upload. This router
covers TN-MTC-05: letting a user review, accept, reject, or reassign those
matches before Stage 4 (output assembly, WBS Section 5 - not yet built)
would run.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.document import Document
from app.models.enums import MatchReviewStatus
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.models.user import User
from app.schemas.matching import MatchOut, MatchReviewRequest, RequirementMatchesOut

router = APIRouter(prefix="/api/tenders", tags=["evidence-matching"])


def _to_match_out(match: RequirementEvidenceMatch) -> MatchOut:
    document = match.document
    return MatchOut(
        id=match.id,
        requirement_id=match.requirement_id,
        document_id=match.document_id,
        document_title=document.title,
        original_filename=document.original_filename,
        file_path=document.file_path,
        category=document.category,
        confidence_score=float(match.confidence_score) if match.confidence_score is not None else None,
        match_type=match.match_type,
        review_status=match.review_status,
        reviewed_at=match.reviewed_at,
    )


@router.get("/{tender_id}/matches", response_model=list[RequirementMatchesOut])
def list_matches(
    tender_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Requirement-by-requirement view of every candidate evidence match,
    for the review UI (TN-MTC-05) to render before final output generation."""
    tender = db.get(Tender, tender_id)
    if tender is None:
        raise HTTPException(status_code=404, detail="Tender not found")

    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender_id, Requirement.evidence_required.is_(True))
        .order_by(Requirement.page_number)
        .all()
    )

    return [
        RequirementMatchesOut(
            requirement_id=req.id,
            page_number=req.page_number,
            section_name=req.section_name,
            description=req.description,
            evidence_description=req.evidence_description,
            matches=[_to_match_out(m) for m in req.evidence_matches],
        )
        for req in requirements
    ]


@router.post("/matches/{match_id}/review", response_model=MatchOut)
def review_match(
    match_id: uuid.UUID,
    body: MatchReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match = db.get(RequirementEvidenceMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")

    if body.action == "accept":
        match.review_status = MatchReviewStatus.ACCEPTED
    elif body.action == "reject":
        match.review_status = MatchReviewStatus.REJECTED
    else:  # reassign
        if body.reassign_document_id is None:
            raise HTTPException(
                status_code=400, detail="reassign_document_id is required to reassign a match"
            )
        new_document = db.get(Document, body.reassign_document_id)
        if new_document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        match.document_id = new_document.id
        match.confidence_score = None  # manually chosen, not a similarity score
        match.review_status = MatchReviewStatus.REASSIGNED

    match.reviewed_by = current_user.id
    match.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(match)
    return _to_match_out(match)
