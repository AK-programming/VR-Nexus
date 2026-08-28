"""
Task 2.2 - TenderChunk model
Linked requirements: TN-ING-03, TN-ING-04, TN-ING-05

Deliberately a separate table from `Chunk` (Task 1.1.3). `Chunk` belongs to
the Evidence Library (Task 6.1) - it stores ~800-token passages of Case
Study / Methodology / Company documents, keyed to a `Document` row, and is
queried later for evidence matching (Stage 3).

`TenderChunk` stores ~2000-token, page-bounded, overlapping passages of an
*uploaded tender/RFP itself* (Stage 1), keyed to a `Tender` row, and is
consumed by the Stage 2 LLM extraction pipeline (Task 3.1) one chunk at a
time. Different owner, different token size, different overlap, different
downstream consumer - conflating the two tables would make both harder to
reason about.
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


class TenderChunk(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "tender_chunks"

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # TN-ING-03: which detected section this chunk falls in (SPN, Instructions
    # to Proposers, PDS, Evaluation Criteria, Section VII, Annexes, or the
    # fallback "General/Front Matter").
    section: Mapped[str] = mapped_column(String(255), nullable=False)

    # TN-ING-02: exact page numbers this chunk's text was drawn from,
    # computed from real per-page token offsets (not just the section's
    # overall page range) - see app/services/chunking.py.
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # TN-ING-04: how many tokens at the start of this chunk are duplicated
    # from the tail of the previous chunk (0 for the first chunk in a
    # section). Kept explicit rather than implied, so Stage 2 dedup logic
    # (3.2.2) can trust it instead of recomputing.
    overlap_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Populated by Stage 2/3 later if this chunk's text itself ever needs
    # semantic search (e.g. re-matching); optional and unused by Task 2.2.
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(_settings.EMBEDDING_DIM), nullable=True
    )

    # --- relationships ---
    tender: Mapped["Tender"] = relationship(back_populates="tender_chunks")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<TenderChunk id={self.id} tender_id={self.tender_id} "
            f"index={self.chunk_index} pages={self.page_start}-{self.page_end}>"
        )
