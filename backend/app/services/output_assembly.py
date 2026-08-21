"""
Task 5 - Output Assembly & Folder Creation (Stage 4)
Linked requirements: TN-OUT-01, TN-OUT-02, TN-OUT-03, TN-OUT-04

Runs after Stage 3 (matching, app/services/matching.py) as the last
automatic step in the upload pipeline (TRK-03's "Report -> Assemble
Folder", right before the "Review" stage a sales manager does by hand).
It has three jobs:

  5.1  build the multi-sheet Excel tracker (TN-OUT-01)
  5.2  assemble the {TenderName}_{Date} root folder + zip it (TN-OUT-02/03/04)
  5.3  optionally render a .docx/.pdf summary alongside it (TN-OUT-05)

run_output_assembly() is the entry point, called once automatically from
the upload pipeline and again from the /finalize endpoint (Task 4.2.2's
review flow) once a sales manager has accepted/rejected/reassigned
matches - so the package on disk reflects their decisions, not just the
raw auto-matching output.
"""
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import MatchReviewStatus, MatchType, TenderStatus
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.tender import Tender
from app.services.progress import publish_progress

_HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_BODY_FONT = Font(name="Arial", size=10)
_WRAP = Alignment(wrap_text=True, vertical="top")

_MAIN_HEADERS = [
    "Page Number", "Section", "Clause Ref", "Description", "Mandatory Flag",
    "Evaluation Impact", "Marks", "Evidence Required", "Matched File Path", "Remarks",
]


def sanitize_filename(name: str) -> str:
    """Strip characters that are illegal (or awkward) in a Windows/macOS/Linux
    path, for the {TenderName}_{Date} directory TN-OUT-02 asks for."""
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name).strip().strip(".")
    return cleaned or "Tender"


def _select_output_match(requirement: Requirement) -> tuple[Optional[RequirementEvidenceMatch], bool]:
    """Picks the single match to print in the Main Sheet's "Matched File
    Path" column (TN-OUT-01) for one requirement, and whether that pick
    was actually reviewed by a person.

    Preference order: a match a sales manager already accepted or
    reassigned (TN-MTC-05) wins outright. Otherwise fall back to the best
    still-pending auto/suggested candidate, so a package built before
    review isn't just a wall of "Missing". Rejected and Missing-type
    matches never get printed here."""
    live = [m for m in requirement.evidence_matches if m.review_status != MatchReviewStatus.REJECTED]

    reviewed = [m for m in live if m.review_status in (MatchReviewStatus.ACCEPTED, MatchReviewStatus.REASSIGNED)]
    if reviewed:
        return reviewed[0], True

    candidates = [m for m in live if m.match_type != MatchType.MISSING]
    if candidates:
        best = max(candidates, key=lambda m: (m.confidence_score or 0))
        return best, False

    return None, False


def generate_excel_tracker(db: Session, tender: Tender, requirements: list[Requirement]) -> Path:
    """TN-OUT-01 - Main Sheet, Summary Sheet, Instructions Sheet."""
    wb = Workbook()

    # --- 5.1.1 Main Sheet ---
    main = wb.active
    main.title = "Main Sheet"
    main.append(_MAIN_HEADERS)
    for col in range(1, len(_MAIN_HEADERS) + 1):
        cell = main.cell(row=1, column=col)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL

    for requirement in requirements:
        match, reviewed = _select_output_match(requirement)
        if not requirement.evidence_required:
            matched_path = ""
        elif match is not None:
            matched_path = match.document.file_path + ("" if reviewed else "  (unreviewed suggestion)")
        else:
            matched_path = "Missing Document"

        remarks = requirement.remarks or ""
        if requirement.evidence_required and match is None:
            remarks = (remarks + " " if remarks else "") + "No evidence document matched - needs manual sourcing."

        main.append([
            requirement.page_number,
            requirement.section_name or "",
            requirement.clause_reference or "",
            requirement.description,
            "Mandatory" if requirement.is_mandatory else ("Advisory" if requirement.is_mandatory is False else ""),
            requirement.evaluation_impact.value if requirement.evaluation_impact else "",
            float(requirement.marks) if requirement.marks is not None else None,
            "Yes" if requirement.evidence_required else "No",
            matched_path,
            remarks,
        ])

    for row in main.iter_rows(min_row=2):
        for cell in row:
            cell.font = _BODY_FONT
            cell.alignment = _WRAP
    widths = [10, 18, 14, 50, 12, 16, 8, 14, 40, 30]
    for i, width in enumerate(widths, start=1):
        main.column_dimensions[get_column_letter(i)].width = width
    main.freeze_panes = "A2"

    # --- 5.1.2 Summary Sheet ---
    # Snapshot counts/marks computed here in Python rather than as live
    # spreadsheet formulas: this is a generated report, not a template the
    # user edits and expects to recalculate, and the set of distinct
    # sections/evaluation types is different for every tender - a fixed
    # formula range can't follow that, and re-deriving it with dynamic
    # array functions risks landing on ones LibreOffice can't evaluate.
    summary = wb.create_sheet("Summary Sheet")
    summary.append(["Tender", tender.name])
    summary.append(["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")])
    summary.append(["Total Requirements", len(requirements)])
    summary.append([])

    by_section: dict[str, dict[str, float]] = {}
    by_impact: dict[str, dict[str, float]] = {}
    for r in requirements:
        section_key = r.section_name or "(No Section)"
        impact_key = r.evaluation_impact.value if r.evaluation_impact else "(Unspecified)"
        marks = float(r.marks) if r.marks is not None else 0.0
        s = by_section.setdefault(section_key, {"count": 0, "marks": 0.0})
        s["count"] += 1
        s["marks"] += marks
        i = by_impact.setdefault(impact_key, {"count": 0, "marks": 0.0})
        i["count"] += 1
        i["marks"] += marks

    summary.append(["Breakdown by Section"])
    summary["A5"].font = Font(name="Arial", bold=True, size=12)
    summary.append(["Section", "Requirement Count", "Total Marks"])
    section_header_row = summary.max_row
    for section_key, stats in sorted(by_section.items()):
        summary.append([section_key, stats["count"], stats["marks"]])
    summary.append([])

    summary.append(["Breakdown by Evaluation Type"])
    summary.cell(row=summary.max_row, column=1).font = Font(name="Arial", bold=True, size=12)
    summary.append(["Evaluation Impact", "Requirement Count", "Total Marks"])
    impact_header_row = summary.max_row
    for impact_key, stats in sorted(by_impact.items()):
        summary.append([impact_key, stats["count"], stats["marks"]])

    for row_num in (1, 2, 3):
        summary.cell(row=row_num, column=1).font = Font(name="Arial", bold=True)
    for row_num in (section_header_row, impact_header_row):
        for col in (1, 2, 3):
            cell = summary.cell(row=row_num, column=col)
            cell.font = _HEADER_FONT
            cell.fill = _HEADER_FILL
    for row in summary.iter_rows():
        for cell in row:
            if cell.font is None or cell.font.name != "Arial":
                cell.font = Font(name="Arial", size=10)
    for i, width in enumerate([28, 20, 14], start=1):
        summary.column_dimensions[get_column_letter(i)].width = width

    # --- 5.1.3 Instructions Sheet ---
    instructions = wb.create_sheet("Instructions")
    lines = [
        ("How to use this tracker", True),
        ("", False),
        ("Main Sheet - one row per requirement extracted from the tender.", False),
        ("\"Evidence Required\" = Yes means the tender asks for a supporting document "
         "(case study, certificate, methodology, etc.) for that requirement.", False),
        ("\"Matched File Path\" shows the evidence file the system attached. "
         "\"Missing Document\" means no confident match was found in the evidence "
         "library and a document needs to be sourced manually.", False),
        ("A path ending in \"(unreviewed suggestion)\" was matched automatically but "
         "not yet confirmed by a reviewer - check it before relying on it.", False),
        ("", False),
        ("Summary Sheet - requirement counts and total marks, broken down by "
         "tender section and by evaluation type (Technical / Financial / "
         "Compliance / Pass-Fail).", False),
        ("", False),
        ("Required Documents folder - copies of every confirmed matched file, "
         "alongside the original tender and this tracker, in the delivered .zip.", False),
    ]
    for text, bold in lines:
        instructions.append([text])
        cell = instructions.cell(row=instructions.max_row, column=1)
        cell.font = Font(name="Arial", bold=bold, size=13 if bold else 10)
    instructions.column_dimensions["A"].width = 100
    for row in instructions.iter_rows():
        for cell in row:
            cell.alignment = _WRAP

    settings = get_settings()
    output_dir = Path(settings.OUTPUT_STORAGE_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / f"{tender.id}_tracker.xlsx"
    wb.save(excel_path)
    return excel_path


def assemble_output_folder(
    db: Session, tender: Tender, excel_path: Path, requirements: list[Requirement]
) -> Path:
    """TN-OUT-02/03 - root {TenderName}_{Date} directory containing the
    original tender, the Excel tracker, and a Required Documents subfolder
    of every confirmed matched file."""
    settings = get_settings()
    date_str = tender.created_at.strftime("%Y-%m-%d") if tender.created_at else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root_name = f"{sanitize_filename(tender.name)}_{date_str}"
    root_dir = Path(settings.OUTPUT_STORAGE_DIR) / root_name

    if root_dir.exists():
        shutil.rmtree(root_dir)  # re-running (e.g. /finalize) replaces a stale draft
    root_dir.mkdir(parents=True)

    original_src = Path(tender.file_path)
    if original_src.exists():
        shutil.copy2(original_src, root_dir / original_src.name)

    shutil.copy2(excel_path, root_dir / f"{sanitize_filename(tender.name)}_Requirement_Tracker.xlsx")

    required_docs_dir = root_dir / "Required Documents"
    required_docs_dir.mkdir()
    copied_documents: set = set()
    for requirement in requirements:
        match, _reviewed = _select_output_match(requirement)
        if match is None or match.document_id in copied_documents:
            continue
        src = Path(match.document.file_path)
        if not src.exists():
            continue
        dest = required_docs_dir / src.name
        if dest.exists():
            dest = required_docs_dir / f"{src.stem}_{str(match.document_id)[:8]}{src.suffix}"
        shutil.copy2(src, dest)
        copied_documents.add(match.document_id)

    return root_dir


def create_zip_archive(folder_path: Path) -> Path:
    """TN-OUT-04 - compress the assembled folder into a downloadable .zip."""
    zip_path = folder_path.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in folder_path.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, arcname=str(Path(folder_path.name) / file_path.relative_to(folder_path)))
    return zip_path


def run_output_assembly(db: Session, tender: Tender) -> dict:
    """Task 5 entry point - mirrors run_matching's (Task 4) shape."""
    from app.services.output_report import generate_summary_report  # local import: avoids a cycle

    requirements = (
        db.query(Requirement)
        .filter(Requirement.tender_id == tender.id, Requirement.duplicate_of_id.is_(None))
        .order_by(Requirement.page_number)
        .all()
    )

    tender.status = TenderStatus.REPORTING
    db.commit()
    publish_progress(str(tender.id), TenderStatus.REPORTING, percent=85, message="Generating Excel tracker")

    excel_path = generate_excel_tracker(db, tender, requirements)

    tender.status = TenderStatus.ASSEMBLING_FOLDER
    db.commit()
    publish_progress(str(tender.id), TenderStatus.ASSEMBLING_FOLDER, percent=92, message="Assembling output folder")

    folder_path = assemble_output_folder(db, tender, excel_path, requirements)
    generate_summary_report(db, tender, requirements, folder_path)  # 5.3 - optional, best-effort
    zip_path = create_zip_archive(folder_path)

    tender.output_folder_path = str(folder_path)
    tender.output_zip_path = str(zip_path)
    tender.status = TenderStatus.READY_FOR_REVIEW
    db.commit()
    publish_progress(
        str(tender.id), TenderStatus.READY_FOR_REVIEW,
        percent=100, message="Output package ready for review",
    )

    return {
        "requirements_packaged": len(requirements),
        "output_folder_path": str(folder_path),
        "output_zip_path": str(zip_path),
    }
