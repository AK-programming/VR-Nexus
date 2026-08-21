"""
Task 5.3 - Summary Report Generation (optional)
Linked requirement: TN-OUT-05

TN-OUT-05 says the system shall "optionally" generate a .docx/.pdf
summary. It's optional in both directions here: this always tries the
.docx (python-docx is already a project dependency, so there's no reason
not to), but the .pdf conversion needs LibreOffice on the host - if it
isn't installed, this logs that and moves on rather than failing the
whole Stage 4 run over an optional artifact.
"""
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from sqlalchemy.orm import Session

from app.models.enums import MatchType
from app.models.requirement import Requirement
from app.models.tender import Tender
from app.services.output_assembly import _select_output_match


def _build_docx(tender: Tender, requirements: list[Requirement]) -> DocxDocument:
    doc = DocxDocument()
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(10)

    title = doc.add_heading(f"Tender Summary Report - {tender.name}", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    doc.add_paragraph(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    total = len(requirements)
    evidence_needed = [r for r in requirements if r.evidence_required]
    matched = missing = 0
    for r in evidence_needed:
        match, _ = _select_output_match(r)
        if match is not None:
            matched += 1
        else:
            missing += 1

    doc.add_heading("Overview", level=2)
    doc.add_paragraph(f"Total requirements extracted: {total}")
    doc.add_paragraph(f"Requirements needing supporting evidence: {len(evidence_needed)}")
    doc.add_paragraph(f"  - Matched: {matched}")
    doc.add_paragraph(f"  - Missing Document (needs manual sourcing): {missing}")

    if missing:
        doc.add_heading("Missing Document Flags", level=2)
        for r in evidence_needed:
            match, _ = _select_output_match(r)
            if match is None:
                ref = r.clause_reference or f"page {r.page_number}" if r.page_number else "unreferenced"
                doc.add_paragraph(f"- ({ref}) {r.description}", style="List Bullet")

    doc.add_heading("Marks by Evaluation Type", level=2)
    by_impact: dict[str, float] = {}
    for r in requirements:
        key = r.evaluation_impact.value if r.evaluation_impact else "(Unspecified)"
        by_impact[key] = by_impact.get(key, 0.0) + float(r.marks or 0)
    for key, total_marks in sorted(by_impact.items()):
        doc.add_paragraph(f"{key}: {total_marks:g} marks", style="List Bullet")

    return doc


def generate_summary_report(
    db: Session, tender: Tender, requirements: list[Requirement], output_folder: Path
) -> dict:
    docx_path = output_folder / f"{tender.name}_Summary.docx".replace("/", "_")
    doc = _build_docx(tender, requirements)
    doc.save(docx_path)

    pdf_path = None
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output_folder), str(docx_path)],
                check=True, capture_output=True, timeout=60,
            )
            candidate = docx_path.with_suffix(".pdf")
            if candidate.exists():
                pdf_path = candidate
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pdf_path = None  # optional artifact - a failed conversion shouldn't fail Stage 4

    return {"docx_path": str(docx_path), "pdf_path": str(pdf_path) if pdf_path else None}
