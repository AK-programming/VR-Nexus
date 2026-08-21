"""
Task 2.1.2 - Page-accurate text & table extraction
Task 2.1.3 - OCR fallback for scanned pages
Linked requirements: TN-ING-02, TN-ING-06

Built on the same PyMuPDF + Tesseract approach Shaheer's prototype
(section_2_1_ingestion.py) used - that core logic was solid and is kept
here largely as-is. What changes: this returns a plain dataclass instead
of writing to a mock DB, so it has no dependency on FastAPI, auth, or any
particular caller, and can be unit-tested (9.1.2) on its own.
"""
from dataclasses import dataclass

import os
import shutil

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

# Only override pytesseract's default lookup ("tesseract" on PATH) when a
# specific binary is configured or when we can locate the Windows install
# location — this keeps OCR working unmodified on the Linux/Docker targets
# named in the Implementation Plan, where "tesseract" is already on PATH
# via the container image, while still supporting local Windows dev boxes.
_tesseract_override = os.getenv("TESSERACT_CMD")
if not _tesseract_override and os.name == "nt":
    _windows_default = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.isfile(_windows_default):
        _tesseract_override = _windows_default
if not _tesseract_override:
    _tesseract_override = shutil.which("tesseract")
if _tesseract_override:
    pytesseract.pytesseract.tesseract_cmd = _tesseract_override

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
                full_page_content = pytesseract.image_to_string(img).strip()
                used_ocr = True

            pages.append(ExtractedPage(page_no=page_index + 1, text=full_page_content, used_ocr=used_ocr))
    finally:
        doc.close()

    return pages
