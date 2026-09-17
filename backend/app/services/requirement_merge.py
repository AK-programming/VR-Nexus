"""Near-duplicate merging for extracted requirements (the MERGING stage).

Why this exists
---------------
Tenders restate the same obligation. SMEDA's RFP lists its eligibility criteria
on pages 21-22 and again, in a "List of Documents" section, on page 81. Its
scoring table appears once as a summary on pages 23-25 and again in detail on
82-85. A bidder has to satisfy each obligation once, so the analyst-authored
tracker carries ONE row per obligation citing every page it appears on
("18 / 78 (PDF 21 / 81)").

Extraction cannot do that on its own, because it runs per chunk and no chunk
contains both copies. The in-run dedup in extraction.py catches only what
survives normalisation (lowercasing, stripping modal prefixes, collapsing
punctuation), which handles a restatement differing by a stray full stop but
not one differing by a whole trailing clause:

    "Must have at least 5 years of verifiable relevant experience"
    "Must have at least 5 years of verifiable relevant experience. Please
     provide proof of verifiable experience as per Applicant Information Form
     attached as Annexure."

Those are one obligation and two different hashes. Before this pass, the
eligibility section of one 125-page tender produced 16 rows for 7 real
requirements, and because coverage was computed per row, two copies of the same
criterion could carry different verdicts: the page 21 copy of "Active Taxpayer
List" read "Not required" while the page 81 copy read "Missing". A reviewer
seeing one obligation answered two ways stops trusting the whole sheet, which
is a worse outcome than either verdict alone.

How it merges
-------------
Embeddings, via the same local fastembed provider the Evidence Library uses, so
this adds no API call and no key. Cosine similarity at or above
`SIMILARITY_THRESHOLD` groups two requirements; grouping is transitive (single
linkage) because a tender that states something three times usually does so in
a chain of pairwise-similar wordings rather than three mutually identical ones.

The kept row is the most specific one, not the first: the longest action wins,
because between "Provide registration documents" and "Provide SECP legal
registration documents, scanned", the second is the one a bid team can act on.
Everything else is unioned, and marks take the MAXIMUM rather than the sum,
since two statements of one criterion are not two criteria (summing them is how
a 100-mark tender was reported as 222).

Deliberately conservative
-------------------------
The threshold is high. A false merge silently destroys an obligation, which is
the one failure this pipeline must not have; a missed merge only leaves a
duplicate row, which a reviewer can see and ignore. So when in doubt this pass
does nothing, and requirements carrying DIFFERENT reference numbers are never
merged however similar their wording, because a tender that numbered them
separately is telling us they are separate. That rule is what keeps the four
distinct obligations under SMEDA's "Evaluation 2.4" (TECH-4 parts a, b and c
plus a presentation row) from collapsing into one.

SIMILARITY_THRESHOLD was 0.93, on the stated assumption that bge-base-en-v1.5
puts genuine restatements "in the high 0.9s" — that number was never checked
against a real run. It wasn't: a real SMEDA run (276 requirements) still
contained several clearly-the-same-obligation pairs uncollapsed — "Provide
proof of at least 5 years of verifiable relevant experience..." stated near-
verbatim in two places, "average annual revenue of PKR 50 million..." likewise,
an Active Taxpayer List requirement restated, a record-keeping clause restated
- exactly the BDS-vs-base-clause restatement pattern this module exists to
catch. The Evidence Library side of this codebase hit the same class of bug at
a different threshold (AUTO_MATCH_THRESHOLD in tender_pipeline.py, assumed
0.85, real matches never exceeded ~0.72) - an unverified assumption about where
this embedding model's scores land, made twice. Lowered to 0.88 as a
conservative first correction, with `_log_near_misses` below recording every
pair that scored in the 0.80-threshold band once. Read those numbers off the
next real run's worker log (search "near-miss") before moving this again -
that is the real distribution, this comment is not.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.requirement import Requirement

logger = logging.getLogger(__name__)

#: Cosine similarity at or above which two requirements are the same
#: obligation. Set high on purpose - see the module docstring on why the
#: failure modes are not symmetric, and on why this moved from 0.93 to 0.88 -
#: a real run, not a re-guess of the same unverified number.
SIMILARITY_THRESHOLD = 0.88

#: Pairs that missed the merge cutoff but were still fairly close get logged
#: once, so the next real run's worker log carries actual cosine numbers for
#: known-duplicate-shaped pairs instead of another assumption about where they
#: land. Purely diagnostic - nothing in this range is merged.
NEAR_MISS_LOG_FLOOR = 0.80

#: Guard against an O(n^2) blow-up on a pathological run. At the intended
#: post-rewrite row counts (tens, not hundreds) this is never reached; it
#: exists so that a regression upstream degrades into "merging skipped" with a
#: warning instead of a worker that appears to hang.
MAX_REQUIREMENTS_FOR_MERGE = 600

_PAGE_SPLIT_RE = re.compile(r"\s*/\s*")


@dataclass
class MergeResult:
    considered: int
    merged_away: int
    groups: int

    @property
    def remaining(self) -> int:
        return self.considered - self.merged_away


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _reference_conflict(a: Requirement, b: Requirement) -> bool:
    """True when both rows carry a reference and the two disagree.

    A tender that numbered two items separately is asserting they are separate
    obligations, and that assertion outranks any similarity score. One row
    having no reference is not a conflict: an unnumbered restatement of a
    numbered clause is exactly the case worth merging.
    """
    ref_a = (a.clause_reference or "").strip().lower()
    ref_b = (b.clause_reference or "").strip().lower()
    if not ref_a or not ref_b:
        return False
    if ref_a == ref_b:
        return False
    # Treat one reference containing the other as agreement ("ITB 7.1" against
    # "BDS Clause 6 / ITB 7.1"), which is how the same clause gets cited at
    # different levels of detail in different parts of a document.
    return ref_a not in ref_b and ref_b not in ref_a


def _merge_pages(rows: list[Requirement]) -> str | None:
    """Union of every page label, in document order, rendered the way the
    analyst trackers do ("21-22 / 81").

    Sorted by leading page number rather than by the order the rows happen to
    come out of the grouping, so a reader follows the citation through the
    document instead of being handed "81 / 21-22". A label with no digits sorts
    last rather than crashing the key.
    """
    seen: list[str] = []
    for r in rows:
        for part in _PAGE_SPLIT_RE.split(r.page_label or ""):
            part = part.strip()
            if part and part not in seen:
                seen.append(part)

    def sort_key(label: str) -> tuple[int, str]:
        match = re.search(r"\d+", label)
        return (int(match.group()) if match else 10**6, label)

    return " / ".join(sorted(seen, key=sort_key))[:50] or None


def _merge_group(rows: list[Requirement]) -> Requirement:
    """Fold a group into its most specific member and return the survivor."""
    # Most specific = longest action. Ties break toward the earlier page so the
    # survivor is stable across runs rather than dependent on query order.
    keeper = max(rows, key=lambda r: (len(r.description or ""), -(r.page_number or 10**6)))
    others = [r for r in rows if r is not keeper]

    keeper.page_label = _merge_pages(rows)
    if keeper.page_number is None:
        keeper.page_number = next((r.page_number for r in rows if r.page_number is not None), None)
    else:
        keeper.page_number = min(r.page_number for r in rows if r.page_number is not None)

    if not (keeper.clause_reference or "").strip():
        keeper.clause_reference = next(
            (r.clause_reference for r in others if (r.clause_reference or "").strip()), None
        )

    # Marks: the MAXIMUM, never the sum. Two statements of one criterion are
    # one criterion.
    marks = [r.marks for r in rows if r.marks is not None]
    keeper.marks = max(marks) if marks else None

    # Evidence: needed if ANY copy says so, and the named documents unioned,
    # because one copy of a clause often names the certificate while the other
    # only alludes to it.
    keeper.evidence_required = any(r.evidence_required for r in rows)
    documents: list[str] = []
    for r in rows:
        for part in (r.evidence_description or "").split(";"):
            part = part.strip()
            if part and part not in documents:
                documents.append(part)
    keeper.evidence_description = "; ".join(documents) or None

    # Remarks: union, since the analyst judgement in one copy's remarks is not
    # necessarily in the other's.
    remarks: list[str] = []
    for r in rows:
        text = (r.remarks or "").strip()
        if text and text not in remarks:
            remarks.append(text)
    keeper.remarks = "\n".join(remarks) or None

    # A merged row is worth a reviewer's eye: the merge is a judgement call and
    # this is what makes it visible rather than silent.
    if others:
        keeper.needs_manual_review = True

    return keeper


def merge_duplicates(db: Session, tender_id, threshold: float = SIMILARITY_THRESHOLD) -> MergeResult:
    """Collapse near-duplicate requirements for one tender, in place.

    Never raises. Merging is a quality improvement on an already-complete
    extraction, so a failure here (no embedding model on the box, an unexpected
    row shape) must leave the un-merged requirements standing rather than fail
    the run: duplicated rows are a usable tracker, no tracker is not.
    """
    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender_id, Requirement.duplicate_of_id.is_(None))
        .order_by(Requirement.page_number, Requirement.created_at)
        .all()
    )
    total = len(requirements)
    if total < 2:
        return MergeResult(considered=total, merged_away=0, groups=0)

    if total > MAX_REQUIREMENTS_FOR_MERGE:
        logger.warning(
            "Tender %s has %s requirements, above the %s merge ceiling; skipping near-duplicate "
            "merging. This usually means extraction over-produced and should be investigated.",
            tender_id, total, MAX_REQUIREMENTS_FOR_MERGE,
        )
        return MergeResult(considered=total, merged_away=0, groups=0)

    try:
        from app.services.library import embeddings

        vectors = embeddings.get_provider().embed_documents(
            [r.description or "" for r in requirements]
        )
    except Exception:
        logger.exception(
            "Tender %s: could not embed requirements, leaving them un-merged.", tender_id
        )
        return MergeResult(considered=total, merged_away=0, groups=0)

    if len(vectors) != total:
        logger.warning(
            "Tender %s: embedder returned %s vectors for %s requirements; skipping merge.",
            tender_id, len(vectors), total,
        )
        return MergeResult(considered=total, merged_away=0, groups=0)

    # Single-linkage grouping via union-find. Transitive on purpose: a clause
    # stated three times tends to form a chain of pairwise-similar wordings
    # rather than three mutually identical ones.
    parent = list(range(total))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    near_misses: list[tuple[float, int, int]] = []
    for i in range(total):
        for j in range(i + 1, total):
            if _reference_conflict(requirements[i], requirements[j]):
                continue
            score = _cosine(vectors[i], vectors[j])
            if score >= threshold:
                union(i, j)
            elif score >= NEAR_MISS_LOG_FLOOR:
                near_misses.append((score, i, j))

    if near_misses:
        near_misses.sort(reverse=True)
        for score, i, j in near_misses[:20]:
            logger.info(
                "Tender %s: near-miss merge (%.4f, below %.2f threshold): %r <-> %r",
                tender_id, score, threshold,
                (requirements[i].description or "")[:80],
                (requirements[j].description or "")[:80],
            )

    clusters: dict[int, list[int]] = {}
    for i in range(total):
        clusters.setdefault(find(i), []).append(i)

    merged_away = 0
    groups = 0
    for members in clusters.values():
        if len(members) < 2:
            continue
        groups += 1
        rows = [requirements[i] for i in members]
        keeper = _merge_group(rows)
        for row in rows:
            if row is keeper:
                continue
            # Tombstoned rather than deleted: duplicate_of_id already exists on
            # the model for exactly this, the evidence matches hanging off the
            # row stay referentially intact, and a reviewer who disagrees with a
            # merge can still see what was folded in. Every consumer filters on
            # duplicate_of_id IS NULL.
            row.duplicate_of_id = keeper.id
            merged_away += 1
        logger.info(
            "Tender %s: merged %s duplicate(s) into %r (pages %s).",
            tender_id, len(rows) - 1, (keeper.description or "")[:60], keeper.page_label,
        )

    db.commit()
    return MergeResult(considered=total, merged_away=merged_away, groups=groups)
