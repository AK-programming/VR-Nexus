"""
Task 2.1.2 - Page-accurate text & table extraction
Task 2.1.3 - OCR fallback for scanned pages
Linked requirements: TN-ING-02, TN-ING-06

Built on the same PyMuPDF + Tesseract approach Shaheer's prototype
(section_2_1_ingestion.py) used - that core logic was solid and is kept
here largely as-is. What changes: this returns a plain dataclass instead
of writing to a mock DB, so it has no dependency on FastAPI, auth, or any
particular caller, and can be unit-tested (9.1.2) on its own.

One deliberate change from the source copy of this module: it set
`pytesseract.pytesseract.tesseract_cmd` to a hardcoded
`C:\\Program Files\\Tesseract-OCR\\tesseract.exe` at import time. Two problems
with that in this merged backend. First, `tesseract_cmd` is global to the
pytesseract module, so that assignment also silently redirected the Evidence
Library's OCR path in app/services/library/parsers/extract.py - and in the
Docker image, where the binary is at /usr/bin/tesseract, it broke both at once
with "tesseract is not installed or it's not in your PATH". Second, it ran on
import, so it applied even to callers that never OCR anything.

It is now opt-in and verified: set TESSERACT_CMD in the environment to point at
the binary, or leave it unset and pytesseract resolves `tesseract` from PATH
(which is what the Docker image wants). A configured path that does not exist is
ignored with a warning rather than silently overriding a working PATH lookup.
"""
import io
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

_TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
if _TESSERACT_CMD:
    if Path(_TESSERACT_CMD).is_file():
        pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
    else:
        logger.warning(
            "TESSERACT_CMD is set to %s, which does not exist. Falling back to "
            "resolving 'tesseract' from PATH.",
            _TESSERACT_CMD,
        )

# Pages with less real text than this are assumed to be scans and get OCR'd
# instead (TN-ING-06). 50 chars is enough to rule out a near-blank page
# while still catching genuinely scanned ones.
OCR_FALLBACK_CHAR_THRESHOLD = 50
OCR_DPI = 300


@dataclass
class ExtractedPage:
    page_no: int  # 1-indexed, matches what a human reading the PDF sees (TN-ING-02)
    text: str
    used_ocr: bool
    # Task: structural section detection. Candidate heading lines on this page,
    # in reading order, detected from the PDF's own font metadata (not regex
    # keyword matching - see _detect_page_headings). Empty for OCR'd pages,
    # since a rasterized page has no font spans to inspect; chunking.py falls
    # back to keyword matching for those.
    headings: list[str] = field(default_factory=list)


# --- structural heading detection --------------------------------------
#
# The original section detector (chunking.SECTION_PATTERNS) only recognizes
# six fixed World Bank / ADB phrases ("Specific Procurement Notice", "Section
# VII", ...). Any tender that uses its own numbered-heading style (which is
# most of them) never matches a single pattern, so the whole document falls
# back to one undifferentiated "General/Front Matter" section - which is
# exactly what happened on the sample EMS RFP (112/167 extracted rows mis-
# labeled). This detector instead asks "does this line of text look like a
# heading on the page it's printed on", using the same signal a human uses:
# it is set in a noticeably larger and/or bolder font than the page's own
# body text, it's short, and it doesn't trail off into a full sentence.
_HEADING_MAX_CHARS = 120
_HEADING_MAX_WORDS = 18


def _detect_page_headings(page: "fitz.Page") -> list[str]:
    """Returns at most one candidate heading for the page: the single most
    visually prominent qualifying line (in reading order for ties). Only one
    is returned, not every bolded phrase on the page, because a tender page
    is full of bolded labels and sub-items that are not section headings -
    picking just the standout line keeps section changes to roughly one per
    real heading instead of firing on every emphasized word. Best-effort: any
    parsing error just yields no heading for that page (caller falls back to
    keyword matching)."""
    try:
        raw = page.get_text("dict")
    except Exception:  # pragma: no cover - defensive, PyMuPDF internals
        return []

    spans: list[dict] = []
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            line_text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if not line_text:
                continue
            sizes = [s.get("size", 0) for s in line.get("spans", []) if s.get("text", "").strip()]
            if not sizes:
                continue
            flags = [s.get("flags", 0) for s in line.get("spans", []) if s.get("text", "").strip()]
            is_bold = any(f & 2**4 for f in flags)  # bit 4 = bold, per PyMuPDF span flags
            spans.append({"text": line_text, "size": max(sizes), "bold": is_bold})

    if not spans:
        return []

    body_size = _median([s["size"] for s in spans])
    candidates: list[tuple[float, str]] = []
    for s in spans:
        text = s["text"]
        if len(text) > _HEADING_MAX_CHARS or len(text.split()) > _HEADING_MAX_WORDS:
            continue
        # Sentence-like lines (ending in a full stop followed by nothing, or a
        # comma) are prose, not headings, regardless of font size.
        if text.endswith((".", ",", ";")) and not text.isupper():
            continue
        larger = s["size"] >= body_size * 1.15
        boldly_larger = s["bold"] and s["size"] >= body_size * 1.05
        if larger or boldly_larger:
            candidates.append((s["size"], text))

    if not candidates:
        return []

    best_size = max(c[0] for c in candidates)
    for size, text in candidates:
        if size == best_size:
            return [text]
    return []  # unreachable, but keeps mypy/pyright happy


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def extract_pdf_pages(file_content: bytes) -> list[ExtractedPage]:
    """Returns one ExtractedPage per page, in order, with page numbers
    preserved exactly as required by TN-ING-02."""
    doc = fitz.open(stream=file_content, filetype="pdf")
    pages: list[ExtractedPage] = []

    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            text = page.get_text("text")
            headings = _detect_page_headings(page)

            table_text = ""
            tables = page.find_tables()
            if tables.tables:
                for table in tables.tables:
                    rows = table.extract()
                    table_text += "\n" + "\n".join(
                        " | ".join(str(cell) if cell else "" for cell in row) for row in rows
                    ) + "\n"

            full_page_content = (text + "\n" + table_text).strip()
            used_ocr = False

            if len(full_page_content) < OCR_FALLBACK_CHAR_THRESHOLD:
                pix = page.get_pixmap(dpi=OCR_DPI)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                try:
                    full_page_content = pytesseract.image_to_string(img).strip()
                    used_ocr = True
                    # A rasterized OCR page has no font spans to detect
                    # headings from - chunking.py falls back to keyword
                    # matching (SECTION_PATTERNS) for these pages.
                    headings = []
                except pytesseract.TesseractNotFoundError:
                    # A missing OCR binary should not lose the whole document:
                    # every other page still extracted fine, and this page is
                    # reported as empty rather than taking the upload down.
                    logger.warning(
                        "Tesseract is not available, so page %s could not be OCR'd. "
                        "Install it or set TESSERACT_CMD to enable scanned-page support.",
                        page_index + 1,
                    )

            pages.append(
                ExtractedPage(
                    page_no=page_index + 1,
                    text=full_page_content,
                    used_ocr=used_ocr,
                    headings=headings,
                )
            )
    finally:
        doc.close()

    return pages
