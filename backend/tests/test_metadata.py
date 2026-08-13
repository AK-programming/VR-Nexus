"""Metadata extraction precedence and content (LIB-IDX-06)."""
from conftest import CASE_STUDY_TEXT

from app.services import metadata


def test_client_is_read_from_a_label():
    result = metadata.extract_heuristic(CASE_STUDY_TEXT, "case.pdf", "case_study")
    assert "Ministry of Health" in result.client


def test_sector_is_read_from_a_label():
    result = metadata.extract_heuristic(CASE_STUDY_TEXT, "case.pdf", "case_study")
    assert result.sector == "Healthcare"


def test_sector_falls_back_to_keyword_matching():
    text = "We delivered a hospital patient records system for clinical staff."
    result = metadata.extract_heuristic(text, "doc.pdf", "case_study")
    assert result.sector == "Healthcare"


def test_service_line_is_inferred():
    text = "A machine learning model was trained to predict demand from historic data."
    result = metadata.extract_heuristic(text, "doc.pdf", "case_study")
    assert result.service_line == "AI & Machine Learning"


def test_specific_geography_beats_a_later_general_one():
    """"Khyber Pakhtunkhwa" is more useful than a bare "Pakistan" further down."""
    text = "The programme covered Khyber Pakhtunkhwa. Reporting went to Pakistan's ministry."
    result = metadata.extract_heuristic(text, "doc.pdf", "case_study")
    assert result.geography == "Khyber Pakhtunkhwa"


def test_keywords_exclude_stopwords():
    result = metadata.extract_heuristic(CASE_STUDY_TEXT, "case.pdf", "case_study")

    assert result.keywords
    for stopword in ("the", "and", "with", "from", "that"):
        assert stopword not in result.keywords


def test_doc_type_defaults_by_category():
    result = metadata.extract_heuristic("Plain text.", "x.pdf", "methodology")
    assert result.doc_type


def test_client_can_be_read_from_a_filename():
    result = metadata.extract_heuristic(
        "No labels anywhere in this body text.", "ACME Corp - Portal Rollout.pdf", "case_study"
    )
    assert result.client == "ACME Corp"


# ---------------------------------------------------------------------------
# Precedence: user > heuristic > LLM
# ---------------------------------------------------------------------------

def test_user_value_is_never_overwritten():
    result = metadata.extract(
        CASE_STUDY_TEXT,
        "case.pdf",
        "case_study",
        user_supplied={"client": "Typed By Hand", "sector": "Education"},
        use_llm=False,
    )

    assert result.client == "Typed By Hand"
    assert result.sector == "Education"


def test_user_supplied_fields_are_not_marked_auto_tagged():
    result = metadata.extract(
        CASE_STUDY_TEXT,
        "case.pdf",
        "case_study",
        user_supplied={"client": "Typed By Hand"},
        use_llm=False,
    )

    assert "client" not in result.auto_tagged_fields


def test_heuristic_fills_are_marked_auto_tagged():
    result = metadata.extract(CASE_STUDY_TEXT, "case.pdf", "case_study", use_llm=False)

    assert "client" in result.auto_tagged_fields
    assert "sector" in result.auto_tagged_fields


def test_keywords_are_parsed_from_a_csv_string():
    result = metadata.extract(
        CASE_STUDY_TEXT,
        "case.pdf",
        "case_study",
        user_supplied={"keywords": "portal, migration , records"},
        use_llm=False,
    )

    assert result.keywords == ["portal", "migration", "records"]


def test_llm_only_fills_fields_still_blank(monkeypatch):
    from app.services import llm

    seen = {}

    def fake_complete_json(prompt, **kwargs):
        seen["prompt"] = prompt
        return {"geography": "Sindh", "client": "Should Be Ignored"}

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", fake_complete_json)

    result = metadata.extract(
        "Body text with no geography mentioned.",
        "doc.pdf",
        "case_study",
        user_supplied={"client": "Known Client"},
        use_llm=True,
    )

    assert result.client == "Known Client"
    assert result.geography == "Sindh"
    assert "geography" in result.auto_tagged_fields

    # The requested-keys line must not name a field that was already known.
    keys_line = next(
        line for line in seen["prompt"].splitlines()
        if line.startswith("Return a JSON object with exactly these keys:")
    )
    assert "client" not in keys_line
    assert "geography" in keys_line


def test_llm_is_skipped_when_nothing_is_missing(monkeypatch):
    from app.services import llm

    called = []
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "complete_json", lambda *a, **k: called.append(1) or {})

    metadata.extract(
        CASE_STUDY_TEXT,
        "case.pdf",
        "case_study",
        user_supplied={
            "doc_type": "Case Study",
            "client": "A",
            "sector": "B",
            "service_line": "C",
            "geography": "D",
            "keywords": "e,f",
        },
        use_llm=True,
    )

    assert not called


def test_all_six_lib_idx_06_attributes_are_covered():
    assert set(metadata.METADATA_FIELDS) == {
        "doc_type", "client", "sector", "service_line", "geography", "keywords",
    }
