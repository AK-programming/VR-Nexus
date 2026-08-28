"""
Section 6.2 - Library Frontend & Training Interface
Linked requirement: LIB-UI-05

Tracks one Train/Memorize run so progress survives a page reload. Separate
from Document.training_status (see JobStage's docstring in enums.py for
why) - this table is the per-run history, that column is the document's
current state.
"""
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import JOB_STAGE_LABELS, JobStage


class IndexJob(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "index_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, name="job_stage"), default=JobStage.QUEUED, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- relationships ---
    document: Mapped["Document"] = relationship(back_populates="jobs")  # noqa: F821

    @property
    def label(self) -> str:
        return JOB_STAGE_LABELS[self.stage]

    def __repr__(self) -> str:
        return f"<IndexJob id={self.id} document_id={self.document_id} stage={self.stage.value}>"
