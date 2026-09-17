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


# Every tender attribute the assembly path reads, for the same reason
# _REQUIREMENT_DEFAULTS exists: a test tender should state only what its case is
# about. This list is also a guard against a recurring failure mode - each time
# the tenders table gained a column the assembler reads (excel_template_override,
# extraction_warnings, and the stated-marks pair), every test in this file
# started failing on a missing attribute rather than on anything it asserts.
# Adding the column here once fixes all of them.
_TENDER_DEFAULTS = dict(
    id="tid", name="Tender", original_filename="tender.pdf",
    reference_id=None, issuing_authority=None, sector=None, location=None,
    tender_value=None, submission_deadline=None, page_count=None,
    total_marks_available=None, total_marks_captured=None,
    stated_technical_marks=None, passing_technical_score=None,
    extraction_warnings=None, excel_template_override=None, uploaded_by=None,
    section_triage=None,
    file_path=None, output_folder_path=None, output_zip_path=None,
)


def _tender(**kwargs):
    data = dict(_TENDER_DEFAULTS)
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

    tender = _tender(
        id="tid-123", name="WASA Rawalpindi", original_filename="tender.pdf",
        reference_id="WASA/RWP/2025/45", issuing_authority="WASA", sector="Water",
        location="Rawalpindi", tender_value=285000000,
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
    # Coverage is found by header rather than by a fixed column index. The index
    # is not stable: the default layout drops the per-member responsibility
    # columns (DPL / PRIME / The Tulepaak / Joint) when no row in this tender
    # fills them, which is the case for this fixture and not for `verbatim`, so
    # Coverage sits at a different column in each. Looking it up by name asserts
    # the same thing without depending on that.
    headers = [cell.value for cell in ws[1]]
    coverage_col = headers.index("Coverage") + 1
    labels = [ws.cell(row=i, column=coverage_col).value for i in range(2, 6)]
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
    tender = _tender(
        id="tid-verbatim", name="NODE RFP", original_filename="tender.pdf",
        reference_id="PK-MOITT-546238", issuing_authority="MoITT", sector="ICT",
        location="Pakistan", page_count=528,
        total_marks_available=20, total_marks_captured=0,
        file_path=None, output_folder_path=None, output_zip_path=None,
    )
    return SimpleNamespace(db=_FakeDB(rows), tender=tender, out=out)


def _tracker(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    folder = scenario.out / scenario.tender.id
    return load_workbook(folder / "requirements_and_matches.xlsx")["Requirements"]


def _cells(ws, row_number):
    """One row as {header: value}.

    Every assertion below looks columns up by name rather than by index. The
    indexes are not stable and should not be: the default layout gained the
    derived owner columns (BD / Technical / Finance-Legal / HR / Joint) and
    drops the legacy partner columns when a tender does not fill them, so the
    same logical column sits at a different position on different tenders.
    Asserting by name tests what these cases are actually about.
    """
    headers = [cell.value for cell in ws[1]]
    return dict(zip(headers, [cell.value for cell in ws[row_number]]))


def test_client_template_columns_appear_in_order(verbatim):
    """The client's own column set, in the client's order, with the three
    VR-Nexus columns after it. Other columns may sit between them - this
    asserts relative order, not absolute position."""
    ws = _tracker(verbatim)
    headers = [cell.value for cell in ws[1]]
    positions = [headers.index(col) for col in CLIENT_TEMPLATE_COLUMNS]
    assert positions == sorted(positions), "client template columns are out of order"
    assert headers.index("Marks") > positions[-1]
    assert [headers[headers.index("Marks") + i] for i in range(3)] == [
        "Marks", "Matched File(s)", "Coverage"
    ]


def test_tender_wording_is_preserved_verbatim(verbatim):
    """The enums cannot hold "1-2", "No/Advisory" or "Financial / Pass-Fail";
    the tracker must still show exactly what the tender said."""
    row = _cells(_tracker(verbatim), 2)
    assert row["Page Number"] == "1-2"
    assert row["Responsibility"] == "Abdul Rehman"
    assert row["Mandatory (Yes/No)"] == "No/Advisory"
    assert row["Evaluation Impact (Pass/Fail / Technical Score / Financial / Compliance)"] == "Financial / Pass-Fail"
    assert row["DPL"] == "Yes"
    assert row["The Tulepaak Responsibility (Yes/No)"] == "No"


def test_extra_tender_fields_become_their_own_columns(verbatim):
    ws = _tracker(verbatim)
    headers = [cell.value for cell in ws[1]]
    # Extras are always last, after every fixed column.
    assert headers[-2:] == ["Lot Number", "Weighting"]
    assert _cells(ws, 2)["Lot Number"] == "3"
    assert _cells(ws, 3)["Weighting"] == "15%"


def test_unstated_fields_are_blank_not_placeholders(verbatim):
    """A tender that states no page, flag, impact or marks leaves empty cells -
    never "N/A"."""
    ws = _tracker(verbatim)
    row = [cell.value for cell in ws[4]]
    for index in (0, 5, 6, 13):
        assert row[index] in ("", None)


# --- marks reconciliation ------------------------------------------------- #
#
# The Summary sheet's "Marks available" is the SUM of what extraction found per
# requirement. A shipped tracker read 222 for a tender whose own evaluation
# section says 100, because that RFP states its scoring table twice and its
# experience bands ("more than 15 years = 10, 10-15 = 5, 7-10 = 1") were added
# together as though one expert could earn all three. Every coverage percentage
# in that pack was computed against 222, and nothing in the workbook said so.
#
# These cover the check that makes the disagreement visible. The `scenario`
# fixture's requirements carry 20 + 10 + 5 = 35 marks, so the stated figure is
# varied against that.

def _summary_rows(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Summary"]
    return {
        str(row[0].value): (row[1].value if len(row) > 1 else None)
        for row in ws.iter_rows()
        if row and row[0].value
    }


def test_marks_check_flags_a_sum_above_the_stated_total(scenario):
    """The 222-against-100 case: the sum is too high, so it is double-counted."""
    scenario.tender.stated_technical_marks = 20
    rows = _summary_rows(scenario)
    assert "⚠ Marks check" in rows
    message = rows["⚠ Marks check"]
    assert "35" in message and "20" in message
    assert "double-counted" in message


def test_marks_check_flags_a_sum_below_the_stated_total(scenario):
    """The opposite failure, which needs the opposite fix, so it must not share
    one vague wording with the case above."""
    scenario.tender.stated_technical_marks = 100
    rows = _summary_rows(scenario)
    assert "incomplete" in rows["⚠ Marks check"]


def test_marks_check_confirms_agreement(scenario):
    scenario.tender.stated_technical_marks = 35
    rows = _summary_rows(scenario)
    assert "⚠ Marks check" not in rows
    assert "35" in rows["Marks check"]


def test_marks_check_is_skipped_when_the_tender_states_no_total(scenario):
    """No claim beats a false claim: with nothing to compare against, the sheet
    says nothing rather than guessing."""
    scenario.tender.stated_technical_marks = None
    rows = _summary_rows(scenario)
    assert "⚠ Marks check" not in rows
    assert "Marks check" not in rows


def test_passing_score_is_shown_when_stated(scenario):
    scenario.tender.passing_technical_score = 70
    rows = _summary_rows(scenario)
    assert rows["Passing technical score"] == 70


# --- Stage A page triage: the "Excluded sections" sheet -------------------- #
#
# Extraction now skips page spans classified as post-award contract terms or
# front matter, which on one reference tender is ~42% of the document. That is
# a large claim to make silently, so the workbook has to show it.

def _sheet_names(scenario):
    _assemble_folder(scenario.db, scenario.tender)
    return load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx").sheetnames


def test_excluded_sections_sheet_is_absent_when_triage_did_not_run(scenario):
    """A sheet that is always present and usually blank stops being read, so it
    only appears when there is something in it. This is also the path every
    tender analysed before triage existed takes."""
    scenario.tender.section_triage = None
    assert "Excluded sections" not in _sheet_names(scenario)


def test_excluded_sections_sheet_is_absent_when_triage_excluded_nothing(scenario):
    scenario.tender.section_triage = {
        "applied": False,
        "reason": "Triage found nothing to exclude.",
        "spans": [{"page_start": 1, "page_end": 126, "kind": "BID_RELEVANT", "label": "All"}],
    }
    assert "Excluded sections" not in _sheet_names(scenario)


def test_excluded_sections_sheet_lists_what_was_skipped(scenario):
    scenario.tender.section_triage = {
        "applied": True,
        "reason": "Excluded 52 of 126 pages (41%) as post-award or non-substantive.",
        "spans": [
            {"page_start": 1, "page_end": 1, "kind": "BID_RELEVANT", "label": "Procurement Notice"},
            {"page_start": 2, "page_end": 3, "kind": "NON_SUBSTANTIVE", "label": "Table of Contents"},
            {"page_start": 4, "page_end": 25, "kind": "BID_RELEVANT", "label": "ITB and Eligibility"},
            {"page_start": 26, "page_end": 75, "kind": "POST_AWARD", "label": "General Conditions of Contract"},
            {"page_start": 76, "page_end": 126, "kind": "BID_RELEVANT", "label": "TOR and Forms"},
        ],
    }
    _assemble_folder(scenario.db, scenario.tender)
    wb = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")
    assert "Excluded sections" in wb.sheetnames
    ws = wb["Excluded sections"]
    rows = [[c.value for c in row] for row in ws.iter_rows()]

    assert rows[0] == ["Pages", "Section", "Why it was skipped"]
    listed = {r[0]: (r[1], r[2]) for r in rows[1:] if r[0]}
    # Only the excluded spans, and a single page renders without a range.
    assert set(listed) == {"2-3", "26-75"}
    assert listed["26-75"][0] == "General Conditions of Contract"
    assert "after award" in listed["26-75"][1]
    assert "Front matter" in listed["2-3"][1]
    # The reason and the "nothing was lost" note both reach the reader.
    trailing = " ".join(str(c) for r in rows for c in r if c)
    assert "52 of 126" in trailing
    assert "still read and chunked" in trailing


def test_excluded_sections_sheet_renders_a_single_page_span(scenario):
    scenario.tender.section_triage = {
        "applied": True, "reason": "Excluded 1 page.",
        "spans": [{"page_start": 7, "page_end": 7, "kind": "NON_SUBSTANTIVE", "label": "Blank"}],
    }
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Excluded sections"]
    assert ws.cell(row=2, column=1).value == "7"


# --- derived responsibility columns (Fix 4) ------------------------------- #
#
# Replaces the hardcoded DPL / PRIME / The Tulepaak trio, which were one
# consortium's partner names baked into the extraction schema and empty in
# every row of any tender where DPL bid alone. Extraction now returns a
# single-valued owner hint, and these columns are derived from it.

def test_owner_hint_marks_exactly_one_department(scenario):
    scenario.db._rows[0].responsibility = "Finance-Legal"
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    row = _cells(ws, 2)
    assert row["Finance / Legal / Admin"] == "Yes"
    assert row["BD / Bid Management"] == "No"
    assert row["Technical / Delivery"] == "No"
    assert row["HR / Resource Management"] == "No"
    assert row["Joint / Multiple"] == "No"


def test_joint_owner_hint_has_its_own_column(scenario):
    """`owner_hint` is single-valued, so "shared" needs somewhere to land
    rather than being spread across every department."""
    scenario.db._rows[0].responsibility = "Joint"
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    assert _cells(ws, 2)["Joint / Multiple"] == "Yes"
    assert _cells(ws, 2)["BD / Bid Management"] == "No"


def test_unrecognised_owner_leaves_every_column_blank(scenario):
    """"Nobody assigned this" and "assigned to BD" have to look different. A
    person's name (what the old schema stored here) is not an owner hint, so it
    must not silently become a "Yes" somewhere."""
    scenario.db._rows[0].responsibility = "Abdul Rehman"
    scenario.db._rows[1].responsibility = None
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    for row_number in (2, 3):
        row = _cells(ws, row_number)
        assert row["BD / Bid Management"] in (None, "")
        assert row["Joint / Multiple"] in (None, "")
    # The raw value is still shown, unchanged, in the Responsibility column.
    assert _cells(ws, 2)["Responsibility"] == "Abdul Rehman"


def test_owner_columns_are_present_even_when_nothing_is_assigned(scenario):
    """Unlike the legacy partner columns, these are not dropped when empty: a
    bid manager needs them there to fill in by hand."""
    for row in scenario.db._rows:
        row.responsibility = None
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    headers = [cell.value for cell in ws[1]]
    for label in ["BD / Bid Management", "Technical / Delivery",
                  "Finance / Legal / Admin", "HR / Resource Management", "Joint / Multiple"]:
        assert label in headers


def test_legacy_partner_columns_are_dropped_when_empty(scenario):
    """The `scenario` fixture is a solo bid: it never sets dpl/prime/the_t, so
    a 687-row sheet should not carry three columns that are blank throughout."""
    _assemble_folder(scenario.db, scenario.tender)
    ws = load_workbook(scenario.out / "tid-123" / "requirements_and_matches.xlsx")["Requirements"]
    headers = [cell.value for cell in ws[1]]
    assert "DPL" not in headers
    assert "PRIME Responsibility (Yes/No)" not in headers
    assert "The Tulepaak Responsibility (Yes/No)" not in headers


def test_legacy_partner_columns_are_kept_when_populated(verbatim):
    """A consortium tender already in the database keeps its own columns."""
    ws = _tracker(verbatim)
    headers = [cell.value for cell in ws[1]]
    assert "DPL" in headers
    assert "PRIME Responsibility (Yes/No)" in headers
