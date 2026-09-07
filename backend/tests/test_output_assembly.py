"""Output assembly — the Stage 4 folder + zip (TN-OUT-02/03/04).

Exercises the real `_assemble_folder` from `app.tasks.tender_pipeline` with no
database, no Redis and no worker: the DB read is a fake whose
`.query(...).filter(...).order_by(...).all()` returns a hand-built list of
requirements, and settings are monkeypatched so the output lands in a tmp dir.
Everything else is the production code path.

Like the rest of this suite, it never opens a socket. It asserts the four
things the Implementation Plan's Stage 4 promises and the earlier build did not
deliver: a multi-sheet workbook (Requirements / Summary / Evidence Matches /
Instructions), the original tender copied in, a Required Documents folder
holding exactly the covered evidence (and not the sub-threshold "missing"
document), and a zip that contains all of it.
"""
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app.models.enums import DocumentCategory, MatchReviewStatus, MatchType
from app.tasks import tender_pipeline
from app.tasks.tender_pipeline import _assemble_folder, _coverage_label, _match_covered


def _doc(title, filename, category, path):
    return SimpleNamespace(
        id=f"doc-{title}", title=title, original_filename=filename,
        category=SimpleNamespace(value=category.value), file_path=str(path),
    )


def _match(doc, match_type, review_status, score):
    return SimpleNamespace(
        document=doc, match_type=match_type, review_status=review_status,
        confidence_score=score,
    )


# Every column the tracker reads, so a test row only states what it cares about.
_REQUIREMENT_DEFAULTS = dict(
    page_number=None, page_label=None, section_name=None, responsibility=None,
    clause_reference=None, description="", is_mandatory=None, mandatory_raw=None,
    evaluation_impact=None, evaluation_impact_raw=None, marks=None,
    evidence_required=False, evidence_description=None, dpl=None, prime=None,
    the_t=None, joint_responsibility=None, remarks="", extra_fields=None,
    evidence_matches=(),
)


def _req(**kwargs):
    data = dict(_REQUIREMENT_DEFAULTS)
    data.update(kwargs)
    return SimpleNamespace(**data)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *a, **k):
        return _FakeQuery(self._rows)

    def commit(self):
        pass


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    a = lib / "a.pdf"; a.write_text("case study A")
    b = lib / "b.docx"; b.write_text("methodology B")
    c = lib / "c.pdf"; c.write_text("company C")
    tender_src = tmp_path / "tender.pdf"; tender_src.write_text("the tender")
    out = tmp_path / "output"; out.mkdir()

    monkeypatch.setattr(
        tender_pipeline, "get_settings",
        lambda: SimpleNamespace(OUTPUT_STORAGE_DIR=str(out)),
    )

    doc_a = _doc("Water Supply", "a.pdf", DocumentCategory.CASE_STUDY, a)
    doc_b = _doc("QA Methodology", "b.docx", DocumentCategory.METHODOLOGY, b)
    doc_c = _doc("Company Profile", "c.pdf", DocumentCategory.COMPANY_DOCUMENT, c)

    reqs = [
        _req(page_number=14, section_name="Technical", clause_reference="5.4",
             description="Technical methodology.", is_mandatory=True,
             evaluation_impact=SimpleNamespace(value="technical"), marks=20,
             evidence_required=True,
             evidence_matches=[_match(doc_a, MatchType.AUTO, MatchReviewStatus.PENDING, 0.91)]),
        _req(page_number=20, section_name="Financial", clause_reference="3.7",
             description="Audited financials.", is_mandatory=False,
             evaluation_impact=SimpleNamespace(value="financial"), marks=10,
             evidence_required=True,
             evidence_matches=[_match(doc_b, MatchType.SUGGESTED, MatchReviewStatus.ACCEPTED, 0.70)]),
        _req(page_number=5, section_name="Eligibility", clause_reference="2.1",
             description="Valid PEC certificate.", is_mandatory=True,
             evaluation_impact=SimpleNamespace(value="compliance"), marks=5,
             evidence_required=True,
             evidence_matches=[_match(doc_c, MatchType.MISSING, MatchReviewStatus.PENDING, 0.30)]),
        _req(page_number=8, section_name="General", clause_reference=None,
             description="Bid validity 90 days.", is_mandatory=None,
             evaluation_impact=None, marks=None, evidence_required=False,
             evidence_matches=[]),
    ]

    tender = SimpleNamespace(
        id="tid-123", name="WASA Rawalpindi", original_filename="tender.pdf",
        reference_id="WASA/RWP/2025/45", issuing_authority="WASA", sector="Water",
        location="Rawalpindi", tender_value=285000000, submission_deadline=None,
        page_count=126, total_marks_available=35, total_marks_captured=30,
        file_path=str(tender_src), output_folder_path=None, output_zip_path=None,
    )
    return SimpleNamespace(db=_FakeDB(reqs), tender=tender, out=out)


def test_coverage_rule_matches_report():
    doc = _doc("x", "x.pdf", DocumentCategory.CASE_STUDY, "/tmp/x")
    assert _match_covered(_match(doc, MatchType.AUTO, MatchReviewStatus.PENDING, 0.9))
    assert _match_covered(_match(doc, MatchType.SUGGESTED, MatchReviewStatus.ACCEPTED, 0.6))
    assert not _match_covered(_match(doc, MatchType.AUTO, MatchReviewStatus.REJECTED, 0.9))
    assert not _match_covered(_match(doc, MatchType.MISSING, MatchReviewStatus.PENDING, 0.3))


def test_workbook_has_the_four_sheets(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    xlsx = scenario.out / "tid-123" / "requirements_and_matches.xlsx"
    assert xlsx.is_file()
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Requirements", "Summary", "Evidence Matches", "Instructions"]


def test_required_documents_holds_only_covered_evidence(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    reqd = scenario.out / "tid-123" / "Required Documents"
    names = sorted(p.name for p in reqd.iterdir())
    assert len(names) == 2
    assert any(n.startswith("case_study__") for n in names)
    assert any(n.startswith("methodology__") for n in names)
    # The sub-threshold MISSING match's document must not be packaged.
    assert not any("company_document" in n for n in names)


def test_original_tender_and_summary_included(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    folder = scenario.out / "tid-123"
    assert (folder / "tender.pdf").is_file()
    import json
    summ = json.loads((folder / "summary.json").read_text())
    assert summ["requirements_total"] == 4
    assert summ["evidence_files_included"] == 2
    assert summ["coverage_percent"] == 85.7


def test_coverage_labels(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    # Coverage is column 16: the client's 13 template columns, then Marks (14),
    # Matched File(s) (15), Coverage (16).
    labels = [ws.cell(row=i, column=16).value for i in range(2, 6)]
    assert labels == ["Covered", "Covered", "Missing", "Not required"]


def test_zip_contains_everything(scenario):
    zip_path = _assemble_folder(scenario.db, scenario.tender)
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert "requirements_and_matches.xlsx" in names
    assert "summary.json" in names
    assert "tender.pdf" in names
    assert any(n.startswith("Required Documents/") for n in names)


# --------------------------------------------------------------------------- #
# The tracker template (what the client's own spreadsheet looks like)         #
# --------------------------------------------------------------------------- #
CLIENT_TEMPLATE_COLUMNS = [
    "Page Number",
    "Section Name",
    "Responsibility",
    "Reference Number",
    "Clause / Requirement Description",
    "Mandatory (Yes/No)",
    "Evaluation Impact (Pass/Fail / Technical Score / Financial / Compliance)",
    "DPL",
    "PRIME Responsibility (Yes/No)",
    "The Tulepaak Responsibility (Yes/No)",
    "Joint Responsibility (Yes/No)",
    "Evidence / Document Required",
    "Remarks",
]


@pytest.fixture
def verbatim(tmp_path, monkeypatch):
    """A tender whose values are the awkward real ones: a page range, an advisory
    flag, a compound evaluation impact, and a tender-specific extra column."""
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(
        tender_pipeline, "get_settings",
        lambda: SimpleNamespace(OUTPUT_STORAGE_DIR=str(out)),
    )
    rows = [
        _req(page_number=1, page_label="1-2", section_name="SPN",
             responsibility="Abdul Rehman", clause_reference="5",
             description="Interested eligible Proposers may obtain information.",
             is_mandatory=False, mandatory_raw="No/Advisory",
             evaluation_impact_raw="Financial / Pass-Fail",
             evidence_required=True, evidence_description="Test plan/results",
             dpl="Yes", prime="Yes", the_t="No", joint_responsibility="Yes",
             remarks="JV-wide item.", extra_fields={"Lot Number": "3"}),
        _req(page_number=147, page_label="147", section_name="Annex Tech-I",
             clause_reference="1.3", description="Technical methodology.",
             is_mandatory=True, mandatory_raw="Yes",
             evaluation_impact_raw="Technical Score", marks=20,
             dpl="Yes", prime="No", the_t="Yes", joint_responsibility="No",
             extra_fields={"Weighting": "15%"}),
        _req(description="Bid validity 90 days."),
    ]
    tender = SimpleNamespace(
        id="tid-verbatim", name="NODE RFP", original_filename="tender.pdf",
        reference_id="PK-MOITT-546238", issuing_authority="MoITT", sector="ICT",
        location="Pakistan", tender_value=None, submission_deadline=None,
        page_count=528, total_marks_available=20, total_marks_captured=0,
        file_path=None, output_folder_path=None, output_zip_path=None,
    )
    return SimpleNamespace(db=_FakeDB(rows), tender=tender, out=out)


def _tracker(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    folder = scenario.out / scenario.tender.id
    return load_workbook(folder / "requirements_and_matches.xlsx")["Requirements"]


def test_first_columns_match_the_client_template_exactly(verbatim):
    ws = _tracker(verbatim)
    headers = [cell.value for cell in ws[1]]
    assert headers[:13] == CLIENT_TEMPLATE_COLUMNS
    assert headers[13:16] == ["Marks", "Matched File(s)", "Coverage"]


def test_tender_wording_is_preserved_verbatim(verbatim):
    """The enums cannot hold "1-2", "No/Advisory" or "Financial / Pass-Fail";
    the tracker must still show exactly what the tender said."""
    ws = _tracker(verbatim)
    row = [cell.value for cell in ws[2]]
    assert row[0] == "1-2"
    assert row[2] == "Abdul Rehman"
    assert row[5] == "No/Advisory"
    assert row[6] == "Financial / Pass-Fail"
    assert row[7] == "Yes" and row[9] == "No"


def test_extra_tender_fields_become_their_own_columns(verbatim):
    ws = _tracker(verbatim)
    headers = [cell.value for cell in ws[1]]
    assert headers[16:] == ["Lot Number", "Weighting"]
    assert [cell.value for cell in ws[2]][16] == "3"
    assert [cell.value for cell in ws[3]][17] == "15%"


def test_unstated_fields_are_blank_not_placeholders(verbatim):
    """A tender that states no page, flag, impact or marks leaves empty cells -
    never "N/A"."""
    ws = _tracker(verbatim)
    row = [cell.value for cell in ws[4]]
    for index in (0, 5, 6, 13):
        assert row[index] in ("", None)
