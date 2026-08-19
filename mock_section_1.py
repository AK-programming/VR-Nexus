# mock_section_1.py
from pydantic import BaseModel

# Global lists to act as our temporary in-memory database!
DB_TENDERS = []
DB_CHUNKS = []

class MockTender:
    def __init__(self, filename, user_id):
        self.id = len(DB_TENDERS) + 1
        self.filename = filename
        self.uploaded_by_user_id = user_id
        self.status = "Processing"

class MockChunk:
    def __init__(self, tender_id, page_range, section, chunk_index, text, embedding):
        self.tender_id = tender_id
        self.page_range = page_range
        self.section = section
        self.chunk_index = chunk_index
        self.text = text
        self.embedding = embedding

def get_current_user():
    return {"id": 1, "username": "test_manager", "role": "admin"}

def get_db():
    class MockSession:
        def add(self, record):
            if isinstance(record, MockTender):
                DB_TENDERS.append(record)
            elif isinstance(record, MockChunk):
                DB_CHUNKS.append(record)
        def commit(self): pass
        def refresh(self, record): pass
    return MockSession()

class QueryRequest(BaseModel):
    tender_id: int
    question: str
    top_k: int = 5