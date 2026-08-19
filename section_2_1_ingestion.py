# section_2_1_ingestion.py

import io

import fitz  # PyMuPDF
import pytesseract
from PIL import Image


def extract_pdf_pages(file_content: bytes, tender_id: int) -> list:
    """Handles WBS 2.1.2 (Text/Tables) and 2.1.3 (OCR)."""
    doc = fitz.open(stream=file_content, filetype="pdf")

    try:
        if doc.needs_pass:
            raise ValueError("PDF is password-protected and cannot be processed.")

        page_data = []

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text")

            # Table Extraction
            table_text = ""
            try:
                tables = page.find_tables()
                if tables.tables:
                    for table in tables.tables:
                        table_text += "\n" + "\n".join(
                            [" | ".join([str(cell) if cell else "" for cell in row]) for row in table.extract()]
                        ) + "\n"
            except Exception as exc:
                # Don't let one malformed table on one page kill the whole tender.
                print(f"[!] Table extraction failed on page {page_num + 1}: {exc}")

            full_page_content = text + "\n" + table_text

            # OCR Fallback
            if len(full_page_content.strip()) < 50:
                try:
                    pix = page.get_pixmap(dpi=300)
                    img_bytes = pix.tobytes("png")
                    with Image.open(io.BytesIO(img_bytes)) as img:
                        full_page_content = pytesseract.image_to_string(img)
                except pytesseract.TesseractNotFoundError:
                    print(f"[X] Tesseract binary not found; skipping OCR for page {page_num + 1}")
                    full_page_content = full_page_content or "[OCR unavailable - Tesseract not installed]"
                except Exception as exc:
                    print(f"[!] OCR failed on page {page_num + 1}: {exc}")
                    full_page_content = full_page_content or f"[OCR failed on page {page_num + 1}]"

            page_data.append({
                "page_no": page_num + 1,
                "text": full_page_content,
                "tender_id": tender_id
            })

        return page_data
    finally:
        # Was never closed before -> leaked an open file handle / memory
        # for every PDF processed.
        doc.close()