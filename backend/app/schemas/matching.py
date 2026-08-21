"""
Task 4.2 - Match Attachment & Review
Linked requirements: TN-MTC-04, TN-MTC-05
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.models.enums import DocumentCategory, MatchReviewStatus, MatchType


class MatchOut(BaseModel):
    id: uuid.UUID
    requirement_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    original_filename: str
    file_path: str
    category: DocumentCategory
    confidence_score: Optional[float] = None
    match_type: MatchType
    review_status: MatchReviewStatus
    reviewed_at: Optional[datetime] = None


class RequirementMatchesOut(BaseModel):
    requirement_id: uuid.UUID
    page_number: Optional[int] = None
    section_name: Optional[str] = None
    description: str
    evidence_description: Optional[str] = None
    matches: list[MatchOut]


class MatchReviewRequest(BaseModel):
    """TN-MTC-05 - accept/reject a suggested match, or manually reassign it
    to a different evidence document."""

    action: Literal["accept", "reject", "reassign"]
    reassign_document_id: Optional[uuid.UUID] = None
