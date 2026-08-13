"""Case study section resolution (LIB-IDX-02)."""
from conftest import CASE_STUDY_TEXT, make_raw

from app.services.parsers import case_study


def test_resolves_the_six_canonical_sections():
    result = case_study.parse(make_raw(CASE_STUDY_TEXT), use_llm=False)

    names = set(result.section_names)
    for expected in ("Client", "Sector", "Scope", "Challenge", "Solution", "Results"):
        assert expected in names, f"{expected} not resolved; got {sorted(names)}"

    assert not result.used_llm


def test_label_sections_capture_only_their_value():
    """"Client: Ministry of Health" must not swallow the paragraphs after it."""
    result = case_study.parse(make_raw(CASE_STUDY_TEXT), use_llm=False)

    client = next(s for s in result.sections if s.name == "Client")
    assert client.content.strip() == "Ministry of Health, Punjab"

    sector = next(s for s in result.sections if s.name == "Sector")
    assert sector.content.strip() == "Healthcare"


def test_client_and_sector_are_promoted_to_document_metadata():
    result = case_study.parse(make_raw(CASE_STUDY_TEXT), use_llm=False)

    assert result.doc_metadata["client"] == "Ministry of Health, Punjab"
    assert result.doc_metadata["sector"] == "Healthcare"


def test_synonym_headings_map_to_canonical_names():
    text = """Rural Connectivity Programme

Client: Telecom Authority

Background
Coverage in three districts was below ten percent.

Approach
We deployed forty solar-powered relay sites.

Impact
Coverage reached seventy-two percent within a year.
"""
    result = case_study.parse(make_raw(text), use_llm=False)
    names = set(result.section_names)

    assert "Challenge" in names   # Background
    assert "Solution" in names    # Approach
    assert "Results" in names     # Impact


def test_prose_before_the_first_heading_becomes_an_overview():
    result = case_study.parse(make_raw(CASE_STUDY_TEXT), use_llm=False)

    overview = next((s for s in result.sections if s.name == "Overview"), None)
    assert overview is not None
    assert "National Health Portal Modernisation" in overview.content


def test_a_keyword_inside_a_sentence_is_not_a_heading():
    text = """Our Work

The challenge of delivering healthcare at scale is well documented in the
literature, and the solution adopted by most providers has been incremental.
The results of that approach have been mixed across the sector.
"""
    result = case_study.parse(make_raw(text), use_llm=False)

    # Nothing resolved, so it falls back to a single section rather than
    # inventing Challenge/Solution/Results from mid-sentence keywords.
    assert result.section_names == ["Document"]


def test_falls_back_to_a_single_section_when_nothing_resolves():
    result = case_study.parse(make_raw("Just one line of text."), use_llm=False)

    assert len(result.sections) == 1
    assert result.sections[0].name == "Document"
    assert result.warnings


def test_below_three_sections_is_not_accepted_as_a_parse():
    """Two matches is a coincidence, not a structure."""
    text = """Overview

Client: ACME Corp

Some narrative that carries on without any further headings at all, describing
the work in a single undifferentiated block of prose.
"""
    result = case_study.parse(make_raw(text), use_llm=False)
    assert result.section_names == ["Document"]


def test_llm_fallback_is_used_when_headings_are_absent(monkeypatch):
    from app.services import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "complete_json",
        lambda *a, **k: {
            "client": "Water Board",
            "sector": "Water & Sanitation",
            "scope": "Network mapping across two districts.",
            "challenge": "No record of pipe locations existed.",
            "solution": "GIS survey and asset register.",
            "results": "Leak response time halved.",
        },
    )

    result = case_study.parse(make_raw("Unstructured prose with no headings."), use_llm=True)

    assert result.used_llm
    assert "Challenge" in result.section_names
    assert result.doc_metadata["client"] == "Water Board"
    # The verbatim text is kept alongside the model's summaries.
    assert "Full Text" in result.section_names


def test_llm_is_not_called_when_headings_resolve(monkeypatch):
    from app.services import llm

    called = []
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: called.append(1) or {})

    result = case_study.parse(make_raw(CASE_STUDY_TEXT), use_llm=True)

    assert not called, "LLM was called even though the heuristic succeeded"
    assert not result.used_llm


def test_images_are_linked_by_path_not_embedded():
    from app.services.parsers.base import Page, RawDoc

    raw = RawDoc(
        filename="case.pdf",
        pages=[
            Page(number=1, text=CASE_STUDY_TEXT, image_paths=["images/abc/p1_0.png"]),
        ],
    )
    result = case_study.parse(raw, use_llm=False)

    linked = [p for s in result.sections for p in s.image_paths]
    assert "images/abc/p1_0.png" in linked

    # No section content may carry image bytes.
    for section in result.sections:
        assert "data:image" not in section.content
        assert "\x89PNG" not in section.content
