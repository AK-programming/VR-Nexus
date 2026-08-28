"""
Task 1.1.5 - Requirement row model
Linked requirement: TN-EXT-02

One row per requirement extracted from a tender chunk (Task 3.x builds the
extraction logic that populates this table; this file only defines the
schema). Mirrors the JSON schema in the implementation plan almost
field-for-field: page_number, section, clause_reference, description,
is_mandatory, evaluation_impact, marks, evidence_required.

RequirementEvidenceMatch is a separate child table rather than a single
FK on Requirement, because TN-MTC-04/05 need to support more than one
candidate file per requirement (auto-matched, suggested, or missing) and
a per-candidate accept/reject/reassign review trail (TN-MTC-05) - a single
column couldn't hold that history.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EvaluationImpact, MatchReviewStatus, MatchType, RequirementStatus


class Requirement(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "requirements"

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    clause_reference: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    is_mandatory: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    evaluation_impact: Mapped[Optional[EvaluationImpact]] = mapped_column(
        Enum(EvaluationImpact, name="evaluation_impact"), nullable=True
    )
    marks: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    evidence_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # From Task 3.1's extraction (Shaheer) - a responsibility-matrix
    # breakdown specific to this tender's format. Field meanings should
    # be confirmed with whoever defined the extraction schema (Shaheer) -
    # kept as plain text here since the exact business rules for how
    # these are assigned aren't encoded anywhere in the codebase yet.
    responsibility: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    dpl: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    prime: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    the_t: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    joint_responsibility: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[RequirementStatus] = mapped_column(
        Enum(RequirementStatus, name="requirement_status"),
        nullable=False,
        default=RequirementStatus.EXTRACTED,
    )
    needs_manual_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TN-EXT-04: when this row is a deduplicated overlap of another, point at
    # the row it was merged into instead of deleting history outright.
    duplicate_of_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=True
    )

    remarks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- relationships ---
    tender: Mapped["Tender"] = relationship(back_populates="requirements")  # noqa: F821
    evidence_matches: Mapped[list["RequirementEvidenceMatch"]] = relationship(
        back_populates="requirement", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Requirement id={self.id} tender_id={self.tender_id} page={self.page_number}>"


class RequirementEvidenceMatch(Base, UUIDPKMixin, TimestampMixin):
    """Task 1.1.5 (supporting table) - Linked requirements: TN-MTC-03/04/05.

    One row per candidate evidence file matched to a requirement, with its
    confidence score and review outcome. A requirement can have zero, one,
    or several of these (e.g. two suggested case studies to choose between).
    """

    __tablename__ = "requirement_evidence_matches"

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )

    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    match_type: Mapped[MatchType] = mapped_column(Enum(MatchType, name="match_type"), nullable=False)

    review_status: Mapped[MatchReviewStatus] = mapped_column(
        Enum(MatchReviewStatus, name="match_review_status"),
        nullable=False,
        default=MatchReviewStatus.PENDING,
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- relationships ---
    requirement: Mapped["Requirement"] = relationship(back_populates="evidence_matches")
    document: Mapped["Document"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<RequirementEvidenceMatch requirement_id={self.requirement_id} "
            f"document_id={self.document_id} type={self.match_type.value}>"
        )
