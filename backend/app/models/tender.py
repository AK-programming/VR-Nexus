"""
Task 1.1.4 - Tender model
Linked requirement: TN-ING-01

Represents one uploaded tender/RFP and tracks it through all 8 pipeline
stages (TRK-03): Parse -> Chunk -> Extract -> Merge -> Match -> Report ->
Assemble Folder -> Review. The individual extracted requirement rows live
in their own table (Task 1.1.5 - Requirement), linked back here.
"""
import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import TenderStatus


class Tender(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "tenders"

    name: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    status: Mapped[TenderStatus] = mapped_column(
        Enum(TenderStatus, name="tender_status"), nullable=False, default=TenderStatus.UPLOADED
    )

    # TN-EXT-05: e.g. {"technical": 70, "financial": 30}
    evaluation_weighting: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_marks_available: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    total_marks_captured: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    # Top-level tender metadata. Populated best-effort by a single LLM pass over
    # the opening pages during PARSING (see services/extraction.extract_tender_metadata)
    # and correctable by the user via PATCH /api/tenders/{id}. All nullable: an
    # unknown value stays null rather than being guessed.
    reference_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issuing_authority: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    tender_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 2), nullable=True)
    submission_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # TN-OUT-02/03/04: where Stage 4 wrote the assembled folder + zip
    output_folder_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    output_zip_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # --- TRK-02: progress payload fields (Task 7.1) ---
    # `status` above already doubles as "step label" (TRK-03's 8 stages).
    # These add the numeric progress the WebSocket payload reports, and are
    # also what a client reconnecting mid-run (TRK-04) reads back to resume
    # showing the correct state instead of starting from 0%.
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    extracted_requirements_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- failure record (the Processing page's error log) ---
    # `progress_message` carries the failure sentence, but it is overwritten by
    # every stage, so on its own it cannot say *where* a run died or keep the
    # detail once the tender is retried into a new run. These three do:
    #
    #   failed_stage  the stage the run was at when it raised - the last state
    #                 committed by _advance, read back after the rollback in
    #                 _fail, so it is the stage that actually failed and not the
    #                 half-written one.
    #   error_detail  the exception class and message, plus the last few
    #                 traceback frames. Text, not String(500): a stack tail is
    #                 the part that tells a developer which call failed, and
    #                 truncating it to fit a column is what makes an error log
    #                 useless. Capped in code at ERROR_DETAIL_LIMIT.
    #   failed_at     when, so the log can be ordered and aged independently of
    #                 `updated_at`, which a retry moves.
    #
    # All three are cleared on a successful re-run (see the reprocess route), so
    # what is on the row always describes the current attempt.
    failed_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- support handoff ---
    # Set when a user pressed "Contact technical support" on a failed tender and
    # the error was emailed to the support team. Its presence is what flips the
    # error log entry from "here is the technical error + Retry" to the calm
    # "reported, please wait 3-4 days" message a non-technical user should see.
    # Cleared on reprocess, like the rest of the failure record.
    support_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- run identity (cancel/reprocess race guard) ---
    # `run_generation` names which pipeline "attempt" currently owns this row.
    # Cancel and reprocess both bump it the instant a person acts; the worker
    # captures the value at task start and every write it makes back onto this
    # row (_advance, _fail in tasks/tender_pipeline.py) is conditioned on the
    # generation still matching. Without this, a worker that is mid-stage when
    # someone clicks Stop - or Stop, then Retry, before that worker noticed -
    # can silently overwrite whatever the person's action just set, including
    # a second worker's in-progress run after a Retry. See tasks/tender_pipeline
    # for the write side of this guard.
    run_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # The Celery task id of whichever run currently owns this row (set by the
    # worker itself at the top of run_tender_pipeline). Cancel uses it to send
    # a hard revoke on top of the cooperative generation check above - belt and
    # braces, since revoke's terminate is best-effort and pool-dependent, while
    # the generation guard is what actually guarantees correctness either way.
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # --- relationships ---
    uploaded_by_user: Mapped[Optional["User"]] = relationship(  # noqa: F821
        back_populates="uploaded_tenders", foreign_keys=[uploaded_by]
    )
    requirements: Mapped[list["Requirement"]] = relationship(  # noqa: F821
        back_populates="tender", cascade="all, delete-orphan"
    )
    tender_chunks: Mapped[list["TenderChunk"]] = relationship(  # noqa: F821
        back_populates="tender", cascade="all, delete-orphan", order_by="TenderChunk.chunk_index"
    )

    def __repr__(self) -> str:
        return f"<Tender id={self.id} name={self.name!r} status={self.status.value}>"
