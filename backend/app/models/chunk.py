"""
Task 1.1.3 - Chunk model (pgvector)
Linked requirement: LIB-IDX-05

Stores one embedded passage of an Evidence Library document (a Document
row from Task 1.1.2). Text is chunked to ~800 tokens with ~100-token
overlap per LIB-IDX-05; the actual chunking logic is built later as part
of the Task 6.1 indexing pipeline, this file only defines where the
result is stored.

The embedding dimension (768) matches Google's text-embedding-004 model
named in the implementation plan, and is read from settings so it stays
in one place if the embedding model ever changes.
"""
import uuid
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.models.base import Base, TimestampMixin, UUIDPKMixin

_settings = get_settings()


class Chunk(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Which natural section this passage came from - e.g. "Client", "Sector",
    # "Scope", "Challenge", "Solution", "Results" for a case study (LIB-IDX-02),
    # or a phase name for a methodology document (LIB-IDX-03).
    section_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(_settings.EMBEDDING_DIM), nullable=True
    )

    # --- relationships ---
    document: Mapped["Document"] = relationship(back_populates="chunks")  # noqa: F821

    def __repr__(self) -> str:
        return f"<Chunk id={self.id} document_id={self.document_id} index={self.chunk_index}>"
