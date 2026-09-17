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

    # What the tender ITSELF says is on offer, as opposed to
    # total_marks_available above, which is the sum of the marks extraction
    # found per requirement. Two separate numbers on purpose: one shipped
    # tracker reported 222 marks available for a tender whose own evaluation
    # section says 100, because the scoring table appears twice in the document
    # and its experience bands ("more than 15 years = 10, 10-15 = 5, 7-10 = 1")
    # were summed as though a bidder could earn all three. Holding the stated
    # figure separately is what turns that from a plausible-looking number into
    # a detectable disagreement - see _marks_reconciliation in
    # app/tasks/tender_pipeline.py.
    stated_technical_marks: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    passing_technical_score: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

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

    # --- extraction warnings (Stage 2 failed-chunk visibility) ---
    # Set by services/extraction.run_extraction when one or more chunks
    # failed all MAX_EXTRACTION_RETRIES attempts and were dropped rather than
    # failing the whole run (tolerated up to MAX_ACCEPTABLE_CHUNK_FAILURE_RATE).
    # Previously that loss was completely invisible outside the worker log: a
    # reviewer saw a thin tracker with no way to tell "this document genuinely
    # has few requirements" apart from "12 pages were silently dropped". Null
    # when every chunk succeeded. Surfaced in the Excel Summary sheet,
    # summary.json, and the tender detail API. Cleared on reprocess, like the
    # rest of the failure record.
    extraction_warnings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Stage A page triage: which page spans were judged worth extracting from,
    # and whether that judgement was acted on. Shape is
    # {"applied": bool, "reason": str, "spans": [{page_start, page_end, kind,
    # label}]} - see app/services/section_triage.py, which owns it.
    #
    # Persisted rather than recomputed because it is audit material, not a
    # cache: the workbook's "Excluded sections" sheet is built from it, so a
    # reviewer can see exactly which pages extraction skipped and why, and
    # disagree. Null on any tender analysed before triage existed, which reads
    # back as "not applied".
    section_triage: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # --- Excel export customization (per-tender override) ---
    # Same shape as User.default_excel_template (app/schemas/excel_template.
    # ExcelTemplate) but scoped to this one tender - set at the "is the
    # format OK?" check before finalizing, when the user wants THIS tender's
    # output to differ from their saved default without changing that
    # default for every other tender. Null means "use the user's saved
    # default, or the platform default if they haven't set one either".
    # Applying a template (new or changed) regenerates the workbook via
    # rebuild_outputs, so output_zip_path always reflects the current value.
    excel_template_override: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

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
