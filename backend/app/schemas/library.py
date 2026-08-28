"""Pydantic v2 request/response schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import DocumentCategory, DocumentTrainingStatus, JobStage


def _blank_if_none(value):
    """1.1.2 declares the metadata columns nullable, so rows written by another
    subsystem can carry NULL where Section 6 always writes "". Normalise on the
    way out so clients get one shape."""
    return "" if value is None else value


def _empty_list_if_none(value):
    return [] if value is None else value


class MetadataInput(BaseModel):
    """LIB-UI-03 — uploader-supplied metadata. Anything left blank is a
    candidate for auto-tagging (LIB-IDX-06); anything filled in is preserved
    verbatim and never overwritten by the LLM."""

    title: str = ""
    client: str = ""
    sector: str = ""
    service_line: str = ""
    geography: str = ""
    keywords: str = ""  # comma-separated on the wire, stored as a list
    auto_tag: bool = True


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_index: int
    content: str
    section_name: str = ""
    phase: str = ""
    page_number: int = 0
    token_count: int = 0
    image_paths: list[str] = []

    _norm_text = field_validator("section_name", "phase", mode="before")(_blank_if_none)
    _norm_list = field_validator("image_paths", mode="before")(_empty_list_if_none)

    @field_validator("page_number", "token_count", mode="before")
    @classmethod
    def _zero_if_none(cls, value):
        return 0 if value is None else value


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    category: DocumentCategory
    title: str
    doc_type: str
    client: str = ""
    sector: str = ""
    service_line: str = ""
    geography: str = ""
    keywords: list[str] = []
    auto_tagged_fields: list[str]
    training_status: DocumentTrainingStatus
    page_count: int
    chunk_count: int
    training_error: str = ""
    created_at: datetime
    indexed_at: datetime | None

    _norm_text = field_validator(
        "client", "sector", "service_line", "geography", "training_error", "title", mode="before"
    )(_blank_if_none)
    _norm_list = field_validator("keywords", "auto_tagged_fields", mode="before")(
        _empty_list_if_none
    )


class DocumentDetailOut(DocumentOut):
    chunks: list[ChunkOut] = []


class UploadResponse(BaseModel):
    document: DocumentOut
    duplicate_warning: "DuplicateCheckResult | None" = None


class DuplicateMatch(BaseModel):
    document_id: uuid.UUID
    original_filename: str
    title: str
    similarity: float


class DuplicateCheckResult(BaseModel):
    """LIB-UI-06. `is_exact` means an identical file hash — a hard block.
    `near_matches` are semantic near-duplicates the user may override."""

    is_exact: bool = False
    exact_match: DuplicateMatch | None = None
    near_matches: list[DuplicateMatch] = []

    @property
    def has_warning(self) -> bool:
        return self.is_exact or bool(self.near_matches)


class TrainRequest(BaseModel):
    """LIB-UI-04. Empty document_ids trains everything still pending."""

    document_ids: list[uuid.UUID] = Field(default_factory=list)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    stage: JobStage
    progress: int
    message: str
    updated_at: datetime


class TrainResponse(BaseModel):
    jobs: list[JobOut]
    skipped: list[uuid.UUID] = Field(
        default_factory=list,
        description="Already indexed, so not re-queued (LIB-IDX-07).",
    )


class ProgressEvent(BaseModel):
    """Payload pushed over /ws/library/{job_id} (LIB-UI-05)."""

    job_id: uuid.UUID
    document_id: uuid.UUID
    stage: JobStage
    label: str
    progress: int
    message: str = ""


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    original_filename: str
    title: str
    category: DocumentCategory
    section_name: str
    phase: str
    page_number: int
    content: str
    similarity: float
    image_paths: list[str]

    # Set only by the /ask path: whether the generated answer cited this
    # passage. Always false for a plain /search, which does no generation.
    cited: bool = False


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class AskRequest(BaseModel):
    """A question put to the library."""

    question: str = Field(min_length=3)
    category: DocumentCategory | None = None
    limit: int = Field(6, ge=1, le=20)


class AnswerOut(BaseModel):
    """A generated answer plus the passages it was built from.

    `sources` is not decoration: the answer is only trustworthy to the extent a
    reader can check it, so the excerpts travel with it. `grounded` is false
    when the model declined for lack of evidence, cited nothing, or generation
    was unavailable — in each case the sources may still be worth reading.
    """

    question: str
    answer: str
    grounded: bool
    sources: list[SearchHit] = []


UploadResponse.model_rebuild()
