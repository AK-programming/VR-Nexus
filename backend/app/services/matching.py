"""
Task 4 - Evidence Matching Engine (Stage 3)
Linked requirements: TN-MTC-01, TN-MTC-02, TN-MTC-03, TN-MTC-04

For every requirement that needs supporting evidence (TN-MTC-01), this
queries the pre-indexed Evidence Library built in Section 6, reusing the
semantic search that module's own docstring calls out as the
"LIB-UI-07 Stage 3 seam" (app.services.library.search).

TN-MTC-02 metadata filtering: a tender requirement carries no sector/
client/service-line fields of its own (nothing in Task 1.1.5's schema or
Task 3.1's extraction schema produces them), so there is nothing to filter
evidence documents against directly. Instead, keywords are pulled from the
requirement's own text and used to boost documents whose metadata
(sector, service_line, client, keywords) mentions the same words - combined
with the semantic similarity from Stage 6's search into one confidence
score.

TN-MTC-03's thresholds (>=0.85 auto, 0.50-0.84 suggested, <0.50 missing)
are applied to that combined score. TN-MTC-04 (attaching matched file
paths) happens by writing RequirementEvidenceMatch rows - the table
Task 1.1.5 already defined for exactly this purpose.
"""
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import MatchReviewStatus, MatchType, TenderStatus
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.services.library.search import search as library_search
from app.services.progress import publish_progress

# How many semantic candidates are pulled per requirement, and how many of
# the best are kept as match rows for review (TN-MTC-04/05 - the
# RequirementEvidenceMatch model's own docstring calls out "two suggested
# case studies to choose between", so this keeps more than one).
_SEARCH_CANDIDATES = 8
_MATCHES_PER_REQUIREMENT = 3

# TN-MTC-03 thresholds.
_AUTO_THRESHOLD = 0.85
_SUGGESTED_THRESHOLD = 0.50

# TN-MTC-02's metadata-filtering component: a small boost on top of raw
# semantic similarity, kept small since similarity is the primary signal.
_METADATA_BOOST_PER_MATCH = 0.03
_METADATA_BOOST_CAP = 0.12
_METADATA_FIELDS = ("sector", "service_line", "client")

_STOPWORDS = {
    "the", "and", "for", "with", "shall", "system", "document", "documents",
    "provide", "provided", "evidence", "required", "requirement", "this",
    "that", "any", "from", "into", "shall", "will", "have", "each",
}


def _keywords(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{4,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _metadata_boost(document: Document, keywords: set[str]) -> float:
    if not keywords:
        return 0.0
    haystack = " ".join(
        [getattr(document, field) or "" for field in _METADATA_FIELDS]
        + (document.keywords or [])
    ).lower()
    hits = sum(1 for kw in keywords if kw in haystack)
    return min(hits * _METADATA_BOOST_PER_MATCH, _METADATA_BOOST_CAP)


def classify(confidence: float) -> MatchType:
    """TN-MTC-03 thresholds."""
    if confidence >= _AUTO_THRESHOLD:
        return MatchType.AUTO
    if confidence >= _SUGGESTED_THRESHOLD:
        return MatchType.SUGGESTED
    return MatchType.MISSING


def find_matches(db: Session, requirement: Requirement) -> list[tuple[Document, float]]:
    """TN-MTC-01/02 - queries the evidence library for one requirement row.
    Returns (document, confidence) pairs, best first, deduplicated so a
    document with several matching chunks only appears once at its best
    score."""
    query_text = requirement.evidence_description or requirement.description
    hits = library_search(db, query_text, limit=_SEARCH_CANDIDATES)
    keywords = _keywords(f"{query_text} {requirement.section_name or ''}")

    best: dict[UUID, tuple[Document, float]] = {}
    for hit in hits:
        document = db.get(Document, hit.document_id)
        if document is None:
            continue
        confidence = min(hit.similarity + _metadata_boost(document, keywords), 1.0)
        existing = best.get(document.id)
        if existing is None or confidence > existing[1]:
            best[document.id] = (document, confidence)

    ranked = sorted(best.values(), key=lambda pair: pair[1], reverse=True)
    return ranked[:_MATCHES_PER_REQUIREMENT]


def run_matching(db: Session, tender: Tender) -> dict:
    """Task 4 entry point - mirrors run_extraction's (Task 3.1) shape so it
    slots into the same pipeline in app/api/routes/tender.py."""
    requirements = (
        db.query(Requirement)
        .filter(
            Requirement.tender_id == tender.id,
            Requirement.evidence_required.is_(True),
            Requirement.duplicate_of_id.is_(None),
        )
        .order_by(Requirement.page_number)
        .all()
    )
    total = len(requirements)

    tender.status = TenderStatus.MATCHING
    db.commit()
    publish_progress(
        str(tender.id), TenderStatus.MATCHING,
        percent=65, message=f"Matching evidence for {total} requirement(s)",
    )

    matched_count = 0
    missing_count = 0

    for i, requirement in enumerate(requirements, start=1):
        # Re-running matching (e.g. after the library was re-indexed) should
        # refresh stale suggestions but never overwrite a match a reviewer
        # already accepted, rejected, or reassigned (TN-MTC-05).
        (
            db.query(RequirementEvidenceMatch)
            .filter(
                RequirementEvidenceMatch.requirement_id == requirement.id,
                RequirementEvidenceMatch.review_status == MatchReviewStatus.PENDING,
            )
            .delete(synchronize_session=False)
        )

        candidates = find_matches(db, requirement)
        if not candidates:
            requirement.needs_manual_review = True
            missing_count += 1
        else:
            for document, confidence in candidates:
                match_type = classify(confidence)
                if match_type == MatchType.MISSING:
                    missing_count += 1
                else:
                    matched_count += 1
                db.add(RequirementEvidenceMatch(
                    requirement_id=requirement.id,
                    document_id=document.id,
                    confidence_score=round(confidence, 4),
                    match_type=match_type,
                ))

        db.commit()
        percent = 65 + int((i / total) * 10) if total else 75  # 65 -> 75
        publish_progress(
            str(tender.id), TenderStatus.MATCHING,
            percent=percent, message=f"Matched requirement {i} of {total}",
        )

    publish_progress(
        str(tender.id), TenderStatus.MATCHING,
        percent=75,
        message=f"Evidence matching complete: {matched_count} matched, {missing_count} flagged",
    )

    return {"requirements_checked": total, "matched": matched_count, "missing": missing_count}
