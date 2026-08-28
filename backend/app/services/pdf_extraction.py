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
from dataclasses import dataclass
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


def extract_pdf_pages(file_content: bytes) -> list[ExtractedPage]:
    """Returns one ExtractedPage per page, in order, with page numbers
    preserved exactly as required by TN-ING-02."""
    doc = fitz.open(stream=file_content, filetype="pdf")
    pages: list[ExtractedPage] = []

    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            text = page.get_text("text")

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
                except pytesseract.TesseractNotFoundError:
                    # A missing OCR binary should not lose the whole document:
                    # every other page still extracted fine, and this page is
                    # reported as empty rather than taking the upload down.
                    logger.warning(
                        "Tesseract is not available, so page %s could not be OCR'd. "
                        "Install it or set TESSERACT_CMD to enable scanned-page support.",
                        page_index + 1,
                    )

            pages.append(ExtractedPage(page_no=page_index + 1, text=full_page_content, used_ocr=used_ocr))
    finally:
        doc.close()

    return pages
