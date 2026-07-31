"""
Task 1.1.2 - Document model
Linked requirements: LIB-IDX-01..04, LIB-UI-01..06

One shared table covers all three Evidence Library categories (Case
Studies, Methodology Documents, Company Documents) rather than three
separate tables, since LIB-IDX-01..04 differ only in how a file is parsed,
not in what metadata it needs. `category` is what the frontend tabs
(LIB-UI-01) filter on.

DocumentImage is a small child table for LIB-IDX-02: case-study images are
extracted and kept on disk, referenced by path, rather than embedded as
raw pixels in the row itself.
"""
import uuid
from typing import Optional

from sqlalchemy import ARRAY, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import DocumentCategory, DocumentFileType, DocumentTrainingStatus


class Document(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "documents"

    category: Mapped[DocumentCategory] = mapped_column(
        Enum(DocumentCategory, name="document_category"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_type: Mapped[DocumentFileType] = mapped_column(
        Enum(DocumentFileType, name="document_file_type"), nullable=False
    )

    # LIB-UI-06: file hash used for the pre-training duplicate check
    file_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    # LIB-UI-03 / LIB-IDX-06 metadata fields (filled in by the user, or by
    # auto-tagging fallback which is built later as part of the indexing pipeline)
    client: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    service_line: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    geography: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    keywords: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)

    # LIB-UI-05: training/indexing pipeline status shown over WebSocket
    training_status: Mapped[DocumentTrainingStatus] = mapped_column(
        Enum(DocumentTrainingStatus, name="document_training_status"),
        nullable=False,
        default=DocumentTrainingStatus.QUEUED,
    )
    training_error: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # --- relationships ---
    uploaded_by_user: Mapped[Optional["User"]] = relationship(  # noqa: F821
        back_populates="uploaded_documents", foreign_keys=[uploaded_by]
    )
    images: Mapped[list["DocumentImage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(  # noqa: F821
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} category={self.category.value} title={self.title!r}>"


class DocumentImage(Base, UUIDPKMixin, TimestampMixin):
    """LIB-IDX-02: images extracted from a case study, stored on disk and
    linked back to the parent document by path (not stored as pixels)."""

    __tablename__ = "document_images"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caption: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return f"<DocumentImage id={self.id} document_id={self.document_id}>"
