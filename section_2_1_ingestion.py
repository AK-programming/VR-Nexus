# section_2_1_ingestion.py

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io


def extract_pdf_pages(file_content: bytes, tender_id: int) -> list:
    """Handles WBS 2.1.2 (Text/Tables) and 2.1.3 (OCR)."""
    doc = fitz.open(stream=file_content, filetype="pdf")
    page_data = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")

        # Table Extraction
        tables = page.find_tables()
        table_text = ""
        if tables.tables:
            for table in tables.tables:
                table_text += "\n" + "\n".join(
                    [" | ".join([str(cell) if cell else "" for cell in row]) for row in table.extract()]) + "\n"

        full_page_content = text + "\n" + table_text

        # OCR Fallback
        if len(full_page_content.strip()) < 50:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            full_page_content = pytesseract.image_to_string(img)

        page_data.append({
            "page_no": page_num + 1,
            "text": full_page_content,
            "tender_id": tender_id
        })

    return page_data