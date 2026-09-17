"""Tests for the near-duplicate merge (the MERGING stage).

No database and no embedding model: `merge_duplicates` needs both, but every
decision it makes lives in the small pure helpers tested here, which is where
the risk is. A false merge silently destroys an obligation, so the guards
against one are pinned individually.

The fixtures are the real strings from a shipped run, not invented examples.
The eligibility pair below is the one that shipped as two rows carrying two
different coverage verdicts for one requirement.
"""
from dataclasses import dataclass

import pytest

from app.services.requirement_merge import (
    _cosine,
    _merge_group,
    _merge_pages,
    _reference_conflict,
)


@dataclass
class FakeRequirement:
    """Just the attributes the merge helpers touch."""
    description: str = ""
    page_label: str = None
    page_number: int = None
    clause_reference: str = None
    marks: float = None
    evidence_required: bool = False
    evidence_description: str = None
    remarks: str = None
    needs_manual_review: bool = False
    duplicate_of_id: object = None
    id: str = "id"


# --- the guards against a false merge ------------------------------------- #

def test_different_references_never_merge():
    """The important one. Four distinct obligations in one real tender all sit
    under "Evaluation 2.4" (TECH-4 parts a, b, c and a presentation row); their
    wording is similar enough that embeddings alone would group them."""
    a = FakeRequirement(clause_reference="Evaluation 2.4 / TECH-4(a)")
    b = FakeRequirement(clause_reference="Evaluation 2.4 / TECH-4(b)")
    assert _reference_conflict(a, b) is True


def test_same_clause_cited_at_different_detail_still_merges():
    a = FakeRequirement(clause_reference="ITB 7.1")
    b = FakeRequirement(clause_reference="BDS Clause 6 / ITB 7.1")
    assert _reference_conflict(a, b) is False


def test_unnumbered_restatement_of_a_numbered_clause_still_merges():
    """Exactly the case worth merging: the tender numbers a criterion in one
    place and restates it unnumbered in another."""
    numbered = FakeRequirement(clause_reference="Eligibility 2")
    unnumbered = FakeRequirement(clause_reference=None)
    assert _reference_conflict(numbered, unnumbered) is False
    assert _reference_conflict(unnumbered, numbered) is False


def test_distinct_numbered_criteria_never_merge():
    a = FakeRequirement(clause_reference="Eligibility 2")
    b = FakeRequirement(clause_reference="Eligibility 3")
    assert _reference_conflict(a, b) is True


# --- what a merge produces ------------------------------------------------ #

def test_merges_the_real_eligibility_duplicate():
    """The pair that shipped as two rows with two different coverage verdicts."""
    detailed = FakeRequirement(
        id="detailed",
        description=(
            "Must have at least 5 years of verifiable relevant experience. Please provide "
            "proof of verifiable experience as per Applicant Information Form attached as Annexure."
        ),
        page_label="21-22", page_number=21, clause_reference=None,
        evidence_required=False, evidence_description="relevant contracts",
        remarks="Separate from the 35-mark specific-project criterion.",
    )
    terse = FakeRequirement(
        id="terse",
        description="Must have at least 5 years of verifiable relevant experience",
        page_label="81", page_number=81, clause_reference="Eligibility 4",
        evidence_required=True, evidence_description="Annexure-A",
    )

    keeper = _merge_group([terse, detailed])

    # The most specific wording survives, not whichever came first.
    assert keeper is detailed
    # Both locations cited, in document order.
    assert keeper.page_label == "21-22 / 81"
    assert keeper.page_number == 21
    # The reference is inherited from whichever copy carried one.
    assert keeper.clause_reference == "Eligibility 4"
    # Evidence is required if ANY copy says so, and the named documents unioned.
    assert keeper.evidence_required is True
    assert "Annexure-A" in keeper.evidence_description
    assert "relevant contracts" in keeper.evidence_description
    # A merge is a judgement call, so the survivor is flagged for a human.
    assert keeper.needs_manual_review is True


def test_marks_take_the_maximum_never_the_sum():
    """Scoring bands are alternatives for one criterion. Summing them is how a
    100-mark tender was reported as having 222 marks available."""
    bands = [
        FakeRequirement(description="Team Leader, more than 15 years of experience", marks=10),
        FakeRequirement(description="Team Leader, more than 10 up to 15 years", marks=5),
        FakeRequirement(description="Team Leader, more than 7 up to 10 years", marks=1),
    ]
    assert _merge_group(bands).marks == 10


def test_remarks_are_unioned_not_overwritten():
    """Analyst-style judgement in one copy's remarks must not be lost because
    the other copy had none."""
    rows = [
        FakeRequirement(description="Submit the Bid Securing Declaration on stamp paper.",
                        remarks="Validity extends 28 days beyond proposal validity."),
        FakeRequirement(description="Submit the Bid Securing Declaration on PKR 100 stamp paper in favour of SMEDA.",
                        remarks="For a JV, the declaration must name the JV."),
    ]
    merged = _merge_group(rows)
    assert "28 days" in merged.remarks
    assert "JV" in merged.remarks


def test_single_row_group_is_left_untouched():
    """A group of one is not a merge, so it must not be flagged for review."""
    only = FakeRequirement(description="Provide NTN and STRN/PST registrations.",
                           page_label="21", page_number=21)
    keeper = _merge_group([only])
    assert keeper is only
    assert keeper.needs_manual_review is False


# --- page rendering ------------------------------------------------------- #

def test_pages_render_in_document_order():
    rows = [FakeRequirement(page_label="81"), FakeRequirement(page_label="21-22")]
    assert _merge_pages(rows) == "21-22 / 81"


def test_pages_dedupe_and_absorb_already_merged_labels():
    rows = [FakeRequirement(page_label="21-22 / 81"), FakeRequirement(page_label="81"),
            FakeRequirement(page_label="118")]
    assert _merge_pages(rows) == "21-22 / 81 / 118"


def test_pages_tolerate_missing_and_non_numeric_labels():
    assert _merge_pages([FakeRequirement(page_label=None), FakeRequirement(page_label="7")]) == "7"
    assert _merge_pages([FakeRequirement(page_label="Annex A"), FakeRequirement(page_label="12")]) == "12 / Annex A"
    assert _merge_pages([FakeRequirement(page_label=None)]) is None


def test_cosine():
    # Identical vectors come back as 0.9999999999999998, not exactly 1.0, since
    # this is a plain float dot product rather than a numpy one. Harmless at a
    # 0.93 threshold, but worth asserting with a tolerance rather than pinning
    # an exact 1.0 that the arithmetic does not actually produce.
    assert _cosine([1.0, 0.0, 1.0], [1.0, 0.0, 1.0]) == pytest.approx(1.0)
    assert _cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    # A zero vector must not raise; it just never clears the threshold.
    assert _cosine([0.0, 0.0], [1.0, 1.0]) == 0.0
    # And a genuine near-duplicate clears 0.93 while a loosely related pair does
    # not, which is the property the threshold relies on.
    assert _cosine([1.0, 0.9, 0.1], [1.0, 0.95, 0.12]) > 0.93
    assert _cosine([1.0, 0.0, 0.0], [0.3, 0.9, 0.3]) < 0.93
