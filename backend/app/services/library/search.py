"""pgvector semantic search (LIB-UI-06 duplicate detection, LIB-UI-07 Stage 3 seam).

Every query goes straight to PostgreSQL. There is deliberately no in-memory
index and no result cache: a document the worker commits is visible to the very
next search, which is what makes hot-reload (LIB-UI-07) true by construction
rather than by invalidation logic.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
_settings = get_settings()
from app.models import Chunk, Document
from app.models.enums import DocumentCategory, DocumentTrainingStatus
from app.schemas.library import DuplicateCheckResult, DuplicateMatch, SearchHit
from app.services.library import embeddings

logger = logging.getLogger(__name__)

# Text sampled from a document to represent it during near-duplicate detection.
# One embedding of the opening is enough to catch a re-upload of the same asset
# under a new filename; comparing every chunk pair would cost far more for the
# same answer.
DUPLICATE_SAMPLE_CHARS = 4000


def search(
    db: Session,
    query: str,
    category: DocumentCategory | None = None,
    limit: int = 10,
    min_similarity: float = 0.0,
) -> list[SearchHit]:
    """Cosine search over indexed chunks.

    pgvector's `<=>` returns cosine *distance*, so similarity is 1 - distance.
    """
    query = (query or "").strip()
    if not query:
        return []

    vector = embeddings.get_provider().embed_query(query)
    distance = Chunk.embedding.cosine_distance(vector)

    stmt = (
        select(Chunk, Document, distance.label("distance"))
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
        .where(Document.training_status == DocumentTrainingStatus.INDEXED)
        .order_by(distance)
        .limit(limit)
    )
    if category is not None:
        # Filtering on the chunk's denormalised category avoids paying for the
        # join before the vector scan narrows the candidate set.
        stmt = stmt.where(Chunk.category == category)

    hits: list[SearchHit] = []
    for chunk, document, dist in db.execute(stmt).all():
        similarity = 1.0 - float(dist)
        if similarity < min_similarity:
            continue
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=document.id,
                original_filename=document.original_filename,
                title=document.title,
                category=document.category,
                section_name=chunk.section_name,
                phase=chunk.phase,
                page_number=chunk.page_number,
                content=chunk.content,
                similarity=round(similarity, 4),
                image_paths=chunk.image_paths or [],
            )
        )
    return hits


def find_by_hash(
    db: Session, file_hash: str, exclude_id: uuid.UUID | None = None
) -> Document | None:
    stmt = select(Document).where(Document.file_hash == file_hash)
    if exclude_id is not None:
        stmt = stmt.where(Document.id != exclude_id)
    return db.execute(stmt).scalars().first()


def find_near_duplicates(
    db: Session,
    text: str,
    category: DocumentCategory | None = None,
    exclude_id: uuid.UUID | None = None,
    threshold: float | None = None,
    limit: int = 3,
) -> list[DuplicateMatch]:
    """Semantic half of LIB-UI-06 — catches a re-upload that was lightly edited,
    reformatted, or converted to a different file type, none of which a hash
    catches."""
    text = (text or "").strip()
    if not text:
        return []

    cutoff = _settings.DUPLICATE_SIMILARITY_THRESHOLD if threshold is None else threshold
    vector = embeddings.get_provider().embed_query(text[:DUPLICATE_SAMPLE_CHARS])
    distance = Chunk.embedding.cosine_distance(vector)

    stmt = (
        select(Document, distance.label("distance"))
        .join(Chunk, Chunk.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
        .where(Document.training_status == DocumentTrainingStatus.INDEXED)
        .order_by(distance)
        # Over-fetch: several chunks of the same document will rank adjacently
        # and collapse to one match below.
        .limit(limit * 10)
    )
    if category is not None:
        stmt = stmt.where(Chunk.category == category)
    if exclude_id is not None:
        stmt = stmt.where(Document.id != exclude_id)

    best: dict[uuid.UUID, DuplicateMatch] = {}
    for document, dist in db.execute(stmt).all():
        similarity = 1.0 - float(dist)
        if similarity < cutoff:
            break  # ordered by distance, so nothing further can qualify
        existing = best.get(document.id)
        if existing is None or similarity > existing.similarity:
            best[document.id] = DuplicateMatch(
                document_id=document.id,
                original_filename=document.original_filename,
                title=document.title,
                similarity=round(similarity, 4),
            )

    return sorted(best.values(), key=lambda m: m.similarity, reverse=True)[:limit]


def check_duplicate(
    db: Session,
    file_hash: str,
    text: str = "",
    category: DocumentCategory | None = None,
    exclude_id: uuid.UUID | None = None,
) -> DuplicateCheckResult:
    """LIB-UI-06 pre-training check.

    An identical sha256 is a hard block — indexing the same bytes twice can only
    dilute retrieval. A semantic near-match is advisory: two case studies for the
    same client genuinely can read alike, so the uploader decides.
    """
    result = DuplicateCheckResult()

    exact = find_by_hash(db, file_hash, exclude_id=exclude_id)
    if exact is not None:
        result.is_exact = True
        result.exact_match = DuplicateMatch(
            document_id=exact.id,
            original_filename=exact.original_filename,
            title=exact.title,
            similarity=1.0,
        )
        # No point paying for an embedding when the answer is already decided.
        return result

    if text:
        try:
            result.near_matches = find_near_duplicates(
                db, text, category=category, exclude_id=exclude_id
            )
        except Exception as exc:
            # A failed similarity check must not block an upload; the hash check
            # above already ran and is the authoritative signal.
            logger.warning("Semantic duplicate check failed: %s", exc)

    return result
