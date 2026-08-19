"""
Request/response shapes for the tender ingestion endpoints (Task 2.1/2.2).
Linked requirements: TN-ING-01..06
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import TenderStatus


class TenderChunkOut(BaseModel):
    chunk_index: int
    section: str
    page_start: int
    page_end: int
    token_count: int
    overlap_tokens: int

    model_config = {"from_attributes": True}


class TenderUploadResponse(BaseModel):
    id: uuid.UUID
    name: str
    original_filename: str
    page_count: int
    status: TenderStatus
    progress_percent: int
    total_chunks: int
    sections_detected: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TenderOut(BaseModel):
    id: uuid.UUID
    name: str
    original_filename: str
    page_count: Optional[int] = None
    status: TenderStatus
    progress_percent: int
    progress_message: Optional[str] = None
    extracted_requirements_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
