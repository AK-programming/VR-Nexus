"""
Enums shared across models. Each is written to Postgres as a native ENUM
type (via SQLAlchemy's Enum(..., name=...)) rather than a plain string
column, so the database itself rejects an invalid value.

NOTE on roles: the SRS (SRS_2.docx) originally specified three roles
(Admin, Manager/Sales Lead, User/Sales Analyst). Per direct instruction,
this build uses only two roles: ADMIN and USER. The "Manager" capabilities
described in the SRS (reviewing/reassigning evidence matches, finalizing
tender folders, training library assets) are folded into the USER role's
permissions rather than a separate role - RBAC middleware (Task 1.2.4)
enforces access at the admin/user level only.
"""
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class DocumentCategory(str, enum.Enum):
    """The three Evidence Library categories from LIB-IDX-01."""

    CASE_STUDY = "case_study"
    METHODOLOGY = "methodology"
    COMPANY_DOCUMENT = "company_document"


class DocumentFileType(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    IMAGE = "image"


class DocumentTrainingStatus(str, enum.Enum):
    """Mirrors the LIB-UI-05 WebSocket progress steps for the Train/Memorize
    action: Parsing -> Tagging -> Generating Embeddings -> Indexing Complete."""

    QUEUED = "queued"
    PARSING = "parsing"
    TAGGING = "tagging"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class TenderStatus(str, enum.Enum):
    """Mirrors the 8 pipeline steps from TRK-03 / the implementation plan's
    WebSocket progress payload: Parse -> Chunk -> Extract -> Merge -> Match
    -> Report -> Assemble Folder -> Review."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EXTRACTING = "extracting"
    MERGING = "merging"
    MATCHING = "matching"
    REPORTING = "reporting"
    ASSEMBLING_FOLDER = "assembling_folder"
    READY_FOR_REVIEW = "ready_for_review"
    FINALIZED = "finalized"
    FAILED = "failed"


class EvaluationImpact(str, enum.Enum):
    """TN-EXT-02 evaluation impact types."""

    PASS_FAIL = "pass_fail"
    TECHNICAL = "technical"
    FINANCIAL = "financial"
    COMPLIANCE = "compliance"


class RequirementStatus(str, enum.Enum):
    """Lifecycle of a single extracted requirement row."""

    EXTRACTED = "extracted"
    MERGED = "merged"
    DUPLICATE = "duplicate"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class MatchType(str, enum.Enum):
    """TN-MTC-03 confidence thresholds."""

    AUTO = "auto"          # confidence >= 0.85
    SUGGESTED = "suggested"  # 0.50 - 0.84
    MISSING = "missing"     # < 0.50


class MatchReviewStatus(str, enum.Enum):
    """TN-MTC-05 - manager/user review of a suggested match."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REASSIGNED = "reassigned"
