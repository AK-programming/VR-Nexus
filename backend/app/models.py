"""SQLAlchemy models for the Evidence Library (WBS 6.1).

The `documents`, `document_images` and `chunks` tables are not ours to invent:
they are WBS 1.1.2 and 1.1.3 (Maryam), both Completed, and Section 6 is a
declared dependent of them. Table names, column names, enum names and the
768-dimension embedding column therefore follow that schema exactly so the
indexing pipeline writes into the same tables Stage 3 matching will read.

What Section 6 adds on top is additive only — columns 1.1.2 has no opinion on
(`doc_type`, `auto_tagged_fields`, `page_count`, `chunk_count`, `error`,
`indexed_at`) plus one table of our own, `index_jobs`, which backs the LIB-UI-05
progress WebSocket. Nothing here renames or drops anything from 1.1.x.
"""
import enum
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Mixins (WBS 1.1.2 `app/models/base.py`)
# ---------------------------------------------------------------------------

class UUIDPKMixin:
    """UUID primary key generated in Python, so no pgcrypto dependency."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Enums (WBS 1.1.2 `app/models/enums.py`)
# ---------------------------------------------------------------------------

class DocumentCategory(str, enum.Enum):
    """LIB-IDX-01 — the three library categories, each with its own upload path.

    Postgres stores the *name* (CASE_STUDY), because SQLAlchemy's Enum defaults
    to names for native enum types and 1.1.2's migration was generated that way.
    The wire format stays the lowercase value, since these are str enums.
    """

    CASE_STUDY = "case_study"
    METHODOLOGY = "methodology"
    COMPANY_DOCUMENT = "company_document"


class DocumentFileType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"


class DocumentTrainingStatus(str, enum.Enum):
    """Document-level lifecycle (1.1.2).

    QUEUED is also the just-uploaded state: a document that has never been
    trained and one waiting for a worker are indistinguishable to a reader, and
    LIB-UI-04 treats both the same way — Train picks them up.
    """

    QUEUED = "queued"
    PARSING = "parsing"
    TAGGING = "tagging"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class JobStage(str, enum.Enum):
    """LIB-UI-05 — per-run stages surfaced over the progress WebSocket.

    Separate from DocumentTrainingStatus on purpose: that column says what a
    document *is*, this says where one particular Train run got to. Re-training
    an indexed document produces a new job that starts at `queued` while the
    document legitimately stays INDEXED until the new run replaces its chunks.
    """

    queued = "queued"
    parsing = "parsing"
    tagging = "tagging"
    embedding = "embedding"
    complete = "complete"
    failed = "failed"


# Labels the UI displays, fixed by LIB-UI-05.
STAGE_LABELS: dict[JobStage, str] = {
    JobStage.queued: "Queued",
    JobStage.parsing: "Parsing",
    JobStage.tagging: "Tagging",
    JobStage.embedding: "Generating Embeddings",
    JobStage.complete: "Indexing Complete",
    JobStage.failed: "Failed",
}

# Document status implied by each job stage, so the two never drift apart.
STAGE_TO_STATUS: dict[JobStage, DocumentTrainingStatus] = {
    JobStage.queued: DocumentTrainingStatus.QUEUED,
    JobStage.parsing: DocumentTrainingStatus.PARSING,
    JobStage.tagging: DocumentTrainingStatus.TAGGING,
    JobStage.embedding: DocumentTrainingStatus.EMBEDDING,
    JobStage.complete: DocumentTrainingStatus.INDEXED,
    JobStage.failed: DocumentTrainingStatus.FAILED,
}


# ---------------------------------------------------------------------------
# Document (WBS 1.1.2)
# ---------------------------------------------------------------------------

class Document(Base, UUIDPKMixin, TimestampMixin):
    """One row per library asset, all three categories in one table."""

    __tablename__ = "documents"

    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, name="document_category"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[DocumentFileType] = mapped_column(
        Enum(DocumentFileType, name="document_file_type"), nullable=False
    )

    # LIB-UI-06 duplicate check. 1.1.2 leaves this nullable and non-unique;
    # Section 6 needs the uniqueness, because it is also the "already indexed,
    # skip it" key behind incremental training (LIB-IDX-07). Adding a constraint
    # is compatible with 1.1.2 — every row it accepts, 1.1.2 accepts too.
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)

    # LIB-UI-03 / LIB-IDX-06 metadata attributes
    client: Mapped[str | None] = mapped_column(String(255), nullable=True, default="")
    sector: Mapped[str | None] = mapped_column(String(255), nullable=True, default="")
    service_line: Mapped[str | None] = mapped_column(String(255), nullable=True, default="")
    geography: Mapped[str | None] = mapped_column(String(255), nullable=True, default="")
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True, default=list)

    training_status: Mapped[DocumentTrainingStatus] = mapped_column(
        Enum(DocumentTrainingStatus, name="document_training_status"),
        nullable=False,
        default=DocumentTrainingStatus.QUEUED,
        index=True,
    )
    training_error: Mapped[str | None] = mapped_column(String(2000), nullable=True, default="")

    # Set once WBS 1.2 lands. Deliberately no ForeignKey yet: `users` does not
    # exist in this deployment, and a FK to a missing table fails at migration
    # time. 1.2 adds the constraint without touching the data.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # --- Section 6 additions (no equivalent in 1.1.2) ----------------------
    doc_type: Mapped[str] = mapped_column(String(128), default="")

    # Which fields a machine filled in, so a reviewer can tell auto-tagged
    # values (LIB-IDX-06) from what the uploader typed.
    auto_tagged_fields: Mapped[list] = mapped_column(JSON, default=list)

    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- relationships ------------------------------------------------------
    images: Mapped[list["DocumentImage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list["IndexJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_auto_tagged(self) -> bool:
        return bool(self.auto_tagged_fields)

    def __repr__(self) -> str:
        return f"<Document id={self.id} category={self.category.value} title={self.title!r}>"


class DocumentImage(Base, UUIDPKMixin, TimestampMixin):
    """LIB-IDX-02 — images extracted from a document, stored on disk and linked
    back by path. Never pixels in the row."""

    __tablename__ = "document_images"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return f"<DocumentImage id={self.id} document_id={self.document_id}>"


# ---------------------------------------------------------------------------
# Chunk (WBS 1.1.3)
# ---------------------------------------------------------------------------

class Chunk(Base, UUIDPKMixin, TimestampMixin):
    """Retrieval unit — ~800 tokens with 100-token overlap (LIB-IDX-05)."""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index", name="uq_chunk_per_doc"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    section_name: Mapped[str | None] = mapped_column(String(255), nullable=True, default="")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)

    # settings.EMBEDDING_DIM is 768 to match this column, not the other way
    # round — see the note in app/config.py.
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.EMBEDDING_DIM), nullable=True)

    # --- Section 6 additions ------------------------------------------------
    # Denormalised from the parent so vector search filters by category without
    # a join (LIB-IDX-01 / TN-MTC-02 metadata filtering).
    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, name="document_category"), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(String(255), default="")  # LIB-IDX-03
    image_paths: Mapped[list] = mapped_column(JSON, default=list)  # LIB-IDX-02

    document: Mapped["Document"] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<Chunk id={self.id} document_id={self.document_id} index={self.chunk_index}>"


# ---------------------------------------------------------------------------
# IndexJob (Section 6 — LIB-UI-04/05)
# ---------------------------------------------------------------------------

class IndexJob(Base, UUIDPKMixin, TimestampMixin):
    """Tracks one Train run so progress survives a page reload."""

    __tablename__ = "index_jobs"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, name="job_stage"), default=JobStage.queued, nullable=False
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")

    document: Mapped["Document"] = relationship(back_populates="jobs")

    @property
    def label(self) -> str:
        return STAGE_LABELS[self.stage]
