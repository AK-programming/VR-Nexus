"""
Task 3.3 - Scoring & Coverage Tracking
Linked requirement: TN-EXT-05

3.3.1 keeps a running tally of the marks captured by extraction (Task
3.1.2) against the tender's evaluation weighting scheme (e.g. 70%
Technical / 30% Financial). Nothing upstream (Task 2's chunking or Task
3.1's extraction) ever populates Tender.evaluation_weighting, so before
tallying anything this also does the one-time work of detecting that
scheme itself, by pattern-matching the "X% <Category>" phrasing tenders
use in their Evaluation Criteria section - the same section Task 2.2's
detect_section_boundaries() already labels.

3.3.2 then reconciles the tally against that weighting: if every mark the
weighting scheme says should exist has actually landed on a Requirement
row, coverage is 100%. A gap either means the LLM missed marks somewhere
(3.1.2) or a chunk failed extraction outright (3.1.3, now visible as
NEEDS_MANUAL_REVIEW rows) - both are surfaced back onto the Tender row so
Stage 4's output (Task 5) can report on them.
"""
import re

from sqlalchemy.orm import Session

from app.models.enums import RequirementStatus
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk

# Matches "70% Technical", "70 % Technical Proposal", "100% Pass/Fail" -
# the "<N>% <Category>" phrasing this codebase's own tender fixtures use
# (see verify_task_2_7.py's "70% Technical, 30% Financial weighting
# applies."). Deliberately only supports this one ordering: a "<Category>
# - <N>%" reverse form is ambiguous to parse safely when several
# categories are listed back-to-back (e.g. "Technical - 70% Financial -
# 30%" - a naive reverse-pattern can pair the wrong number with the
# wrong label), and every real fixture in this codebase uses this order.
_CATEGORY_FRAGMENT = r"(technical|financial|compliance|pass\s*/?\s*fail)"
_WEIGHTING_RE = re.compile(rf"(\d{{1,3}}(?:\.\d+)?)\s*%\s*{_CATEGORY_FRAGMENT}", re.IGNORECASE)


def _canonical_category(label: str) -> str:
    normalized = re.sub(r"\s+", "", label.lower())
    return "pass_fail" if normalized.startswith("pass") else normalized


def detect_evaluation_weighting(db: Session, tender: Tender) -> dict:
    """3.3.1 - scans this tender's chunks for '<N>% <Category>' phrasing
    and returns e.g. {"technical": 70.0, "financial": 30.0}. Prefers
    chunks from a section whose name contains "evaluation" (Task 2.2's
    boundary detector labels one "Evaluation Criteria"), falling back to
    every chunk if none matched that section so this still works on
    tenders where the section name comes out slightly differently.
    """
    chunks = (
        db.query(TenderChunk)
        .filter(TenderChunk.tender_id == tender.id)
        .order_by(TenderChunk.chunk_index)
        .all()
    )
    eval_chunks = [c for c in chunks if "evaluation" in (c.section or "").lower()]
    search_pool = eval_chunks or chunks

    weighting: dict[str, float] = {}
    for chunk in search_pool:
        for match in _WEIGHTING_RE.finditer(chunk.content or ""):
            pct, label = match.group(1), match.group(2)
            weighting[_canonical_category(label)] = float(pct)
        if weighting:
            break  # first chunk with any hits is treated as the authoritative table

    return weighting


def compute_tally(requirements: list[Requirement]) -> dict[str, float]:
    """3.3.1 - running tally of captured marks by evaluation impact
    category, skipping duplicate rows so an overlap-chunk requirement
    counted under two chunks doesn't inflate the total."""
    tally: dict[str, float] = {}
    for r in requirements:
        if r.status == RequirementStatus.DUPLICATE or r.marks is None:
            continue
        key = r.evaluation_impact.value if r.evaluation_impact else "unspecified"
        tally[key] = tally.get(key, 0.0) + float(r.marks)
    return tally


def run_scoring(db: Session, tender: Tender) -> dict:
    """3.3.1 + 3.3.2 entry point: detects/reuses the evaluation weighting
    scheme, tallies captured marks against it, writes
    total_marks_captured / total_marks_available back onto the Tender
    row, and reports whether extracted marks reconcile to 100% of the
    tender's weighting.
    """
    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id)
        .all()
    )

    if not tender.evaluation_weighting:
        detected = detect_evaluation_weighting(db, tender)
        if detected:
            tender.evaluation_weighting = detected

    tally = compute_tally(requirements)
    total_marks_captured = sum(tally.values())

    weighting = tender.evaluation_weighting or {}
    # Weighting percentages sit on the same 0-100 scale as each
    # requirement's own `marks` value (a 70/30 split -> 70 technical
    # marks + 30 financial marks available in total), so summing them
    # directly gives the total marks available.
    total_marks_available = sum(float(v) for v in weighting.values()) if weighting else None

    tender.total_marks_captured = total_marks_captured
    tender.total_marks_available = total_marks_available
    db.commit()

    coverage_percent = None
    fully_reconciled = False
    missing_categories: list[str] = []
    if total_marks_available and total_marks_available > 0:
        coverage_percent = round((total_marks_captured / total_marks_available) * 100, 2)
        fully_reconciled = abs(total_marks_available - total_marks_captured) < 0.01
        for category, expected in weighting.items():
            captured = tally.get(category, 0.0)
            if captured < float(expected) - 0.01:
                missing_categories.append(category)

    manual_review_count = sum(
        1 for r in requirements if r.status == RequirementStatus.NEEDS_MANUAL_REVIEW
    )

    return {
        "tally": tally,
        "evaluation_weighting": weighting,
        "total_marks_captured": total_marks_captured,
        "total_marks_available": total_marks_available,
        "coverage_percent": coverage_percent,
        "fully_reconciled": fully_reconciled,
        "missing_categories": missing_categories,
        "manual_review_count": manual_review_count,
    }
