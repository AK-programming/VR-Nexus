"""Methodology phase splitting (LIB-IDX-03) and company classification (LIB-IDX-04)."""
from conftest import COMPANY_DOC_TEXT, METHODOLOGY_TEXT, make_raw

from app.services.parsers import company, methodology


# ---------------------------------------------------------------------------
# LIB-IDX-03
# ---------------------------------------------------------------------------

def test_splits_on_phase_markers():
    result = methodology.parse(make_raw(METHODOLOGY_TEXT), use_llm=False)

    phases = [s.phase for s in result.sections if s.phase]
    assert len(phases) == 4
    assert phases[0].startswith("Phase 1")
    assert phases[3].startswith("Phase 4")
    assert not result.used_llm


def test_phase_label_lands_on_the_section():
    result = methodology.parse(make_raw(METHODOLOGY_TEXT), use_llm=False)

    inception = next(s for s in result.sections if s.phase.startswith("Phase 1"))
    assert "Inception" in inception.phase
    assert "governance structure" in inception.content


def test_phases_keep_document_order():
    result = methodology.parse(make_raw(METHODOLOGY_TEXT), use_llm=False)

    numbers = [
        s.phase.split()[1].rstrip(":")
        for s in result.sections
        if s.phase.startswith("Phase")
    ]
    assert numbers == ["1", "2", "3", "4"]


def test_text_before_the_first_phase_becomes_an_introduction():
    result = methodology.parse(make_raw(METHODOLOGY_TEXT), use_llm=False)

    intro = next((s for s in result.sections if s.name == "Introduction"), None)
    assert intro is not None
    assert "four sequential phases" in intro.content


def test_marker_line_is_kept_in_the_body():
    """"Phase 2 - Requirements Analysis" is itself useful retrieval text."""
    result = methodology.parse(make_raw(METHODOLOGY_TEXT), use_llm=False)

    section = next(s for s in result.sections if s.phase.startswith("Phase 2"))
    assert "Phase 2" in section.content


def test_step_and_stage_markers_also_split():
    text = """Approach

Step 1 - Discovery
We review existing documentation.

Step 2 - Assessment
We score each system against the criteria.

Step 3 - Recommendation
We deliver a prioritised roadmap.
"""
    result = methodology.parse(make_raw(text), use_llm=False)
    assert len([s for s in result.sections if s.phase]) == 3


def test_numbered_headings_split_when_no_phase_keyword_exists():
    text = """Delivery Model

1. Mobilisation
The team is assembled and onboarded.

2. Baseline Assessment
Current state is documented against the framework.

3. Capacity Building
Training is delivered to nominated staff.
"""
    result = methodology.parse(make_raw(text), use_llm=False)
    assert len([s for s in result.sections if s.phase]) == 3


def test_a_single_marker_is_not_a_structure():
    """One mention of "Phase 1" in a paragraph must not trigger a split."""
    text = (
        "Our methodology is iterative. Phase 1 is described below in detail, and "
        "the remainder of the document discusses governance without further "
        "structural markers of any kind."
    )
    result = methodology.parse(make_raw(text), use_llm=False)

    assert result.section_names == ["Methodology"]
    assert result.warnings


def test_llm_fallback_returns_ordered_phases(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "complete_json",
        lambda *a, **k: {
            "phases": [
                {"name": "Discovery", "content": "We assess the current state."},
                {"name": "Delivery", "content": "We build and deploy."},
            ]
        },
    )

    result = methodology.parse(make_raw("Prose with no markers whatsoever."), use_llm=True)

    assert result.used_llm
    assert [s.phase for s in result.sections if s.phase] == ["Discovery", "Delivery"]


def test_llm_result_with_one_phase_is_rejected(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm, "complete_json", lambda *a, **k: {"phases": [{"name": "X", "content": "y"}]}
    )

    result = methodology.parse(make_raw("Prose with no markers."), use_llm=True)
    assert result.section_names == ["Methodology"]


# ---------------------------------------------------------------------------
# LIB-IDX-04
# ---------------------------------------------------------------------------

def test_company_document_is_not_split_into_sections():
    """LIB-IDX-04 — single-purpose indexing means one logical unit."""
    result = company.parse(make_raw(COMPANY_DOC_TEXT), use_llm=False)
    assert len(result.sections) == 1


def test_registration_is_classified():
    result = company.parse(make_raw(COMPANY_DOC_TEXT, filename="registration.pdf"), use_llm=False)
    assert result.doc_metadata["doc_type"] == "Registration"


def test_certificate_is_classified():
    text = """ISO 9001:2015 CERTIFICATE

This is to certify that the quality management system of DPL Technologies
conforms to ISO 9001:2015.

Certificate No: QMS-2024-0891
Certification Body: Bureau Veritas
Valid until: 30-06-2027
"""
    result = company.parse(make_raw(text, filename="iso9001.pdf"), use_llm=False)
    assert result.doc_metadata["doc_type"] == "Certificate"


def test_tax_filing_is_classified():
    text = """INCOME TAX RETURN

Taxpayer: DPL Technologies (Private) Limited
NTN: 7654321-8
Tax Year: 2024

Filed with the Federal Board of Revenue (FBR).
"""
    result = company.parse(make_raw(text, filename="itr_2024.pdf"), use_llm=False)
    assert result.doc_metadata["doc_type"] == "Tax Filing"
    assert result.doc_metadata["tax_year"] == "2024"


def test_identifiers_are_extracted():
    result = company.parse(make_raw(COMPANY_DOC_TEXT), use_llm=False)

    assert result.doc_metadata["ntn"] == "7654321-8"
    assert "12345" in result.doc_metadata["certificate_number"]
    assert result.doc_metadata["issued_on"] == "15-03-2019"


def test_weak_classification_falls_back_to_the_llm(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"doc_type": "Company Profile"})

    result = company.parse(make_raw("A page of text with no giveaway phrases."), use_llm=True)

    assert result.used_llm
    assert result.doc_metadata["doc_type"] == "Company Profile"


def test_llm_cannot_invent_a_category(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: {"doc_type": "Invented Type"})

    result = company.parse(make_raw("Ambiguous text."), use_llm=True)
    assert result.doc_metadata["doc_type"] == "Company Document"


def test_unclassifiable_document_still_indexes():
    result = company.parse(make_raw("Some text without any identifying phrases."), use_llm=False)

    assert result.doc_metadata["doc_type"] == "Company Document"
    assert len(result.sections) == 1
    assert result.warnings
