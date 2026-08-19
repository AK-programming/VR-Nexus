"""
Task 1.1.4 - Tender model
Linked requirement: TN-ING-01

Represents one uploaded tender/RFP and tracks it through all 8 pipeline
stages (TRK-03): Parse -> Chunk -> Extract -> Merge -> Match -> Report ->
Assemble Folder -> Review. The individual extracted requirement rows live
in their own table (Task 1.1.5 - Requirement), linked back here.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String
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
