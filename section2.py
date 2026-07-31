from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF
import tiktoken
import pytesseract
from PIL import Image
import io


# 1.1.4 & 1.2.4 Mock vode
class MockTender:
    def __init__(self, filename, user_id):
        self.id = 999
        self.filename = filename
        self.uploaded_by_user_id = user_id
        self.status = "Processing"


def get_current_user():
    return {"id": 1, "username": "test_manager", "role": "admin"}


def get_db():
    class MockSession:
        def add(self, record): pass

        def commit(self): pass

        def refresh(self, record): pass

    return MockSession()


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2.1.1
@app.post("/tender")
async def tender(
        file: UploadFile = File(...),
        current_user: dict = Depends(get_current_user),
        db=Depends(get_db)
):
    if file.filename is None or not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF file is required")

    content = await file.read()

    # 2.1.1
    if len(content) > 104857600:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 100MB.")

    new_tender = MockTender(filename=file.filename, user_id=current_user["id"])
    db.add(new_tender)
    db.commit()
    db.refresh(new_tender)

    # 2.1.2
    doc = fitz.open(stream=content, filetype="pdf")
    page_data = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")

        tables = page.find_tables()
        table_text = ""
        if tables.tables:
            for table in tables.tables:
                table_text += "\n" + "\n".join(
                    [" | ".join([str(cell) if cell else "" for cell in row]) for row in table.extract()]) + "\n"

        full_page_content = text + "\n" + table_text

        # 2.1.3
        if len(full_page_content.strip()) < 50:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            full_page_content = pytesseract.image_to_string(img)

        page_data.append({
            "page_no": page_num + 1,
            "text": full_page_content,
            "tender_id": new_tender.id
        })

    new_tender.status = "Parsed"
    db.commit()

    return {
        "message": "Extracted successfully",
        "tender_id": new_tender.id,
        "total_pages": len(page_data)
    }