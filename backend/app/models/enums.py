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


class FeatureKey(str, enum.Enum):
    """The optional sections a USER account can be granted access to.

    Added per a client review meeting: new accounts now start with none of
    these (only the always-on shell - dashboard, activity, settings, profile
    - is visible), and an admin grants each one individually from the Users
    admin page. See app/api/deps.py's require_feature and
    app/api/routes/admin.py for how a grant turns into an enforced check.

    ADMIN accounts never consult this list - require_feature always lets an
    admin through - so this only matters for USER rows. Stored as a plain
    ARRAY(String) column on users.feature_access rather than a native
    Postgres ENUM array, so adding a fifth feature later is a Python-only
    change with no migration touching the enum type itself.
    """

    DOCUMENTS = "documents"
    # Added per a later client follow-up: a narrower grant than DOCUMENTS -
    # lets an account contribute evidence (Upload/Processing tabs) without
    # the full Library view/manage grant. See DocumentsLayout.tsx and
    # Sidebar.tsx on the frontend for how the two are told apart.
    DOCUMENTS_UPLOAD = "documents_upload"
    AI_ASSISTANT = "ai_assistant"
    TENDER_ANALYSIS = "tender_analysis"
    TENDER_TOOLS = "tender_tools"


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


class JobStage(str, enum.Enum):
    """LIB-UI-05 - per-run stages surfaced over the library progress
    WebSocket. Separate from DocumentTrainingStatus on purpose: that column
    says what a document *is* right now, this says where one particular
    Train run got to. Re-training an already-indexed document starts a new
    job at `queued` while the document itself legitimately stays INDEXED
    until the new run finishes and replaces its chunks."""

    QUEUED = "queued"
    PARSING = "parsing"
    TAGGING = "tagging"
    EMBEDDING = "embedding"
    COMPLETE = "complete"
    FAILED = "failed"


# Labels the UI displays, fixed by LIB-UI-05.
JOB_STAGE_LABELS: dict[JobStage, str] = {
    JobStage.QUEUED: "Queued",
    JobStage.PARSING: "Parsing",
    JobStage.TAGGING: "Tagging",
    JobStage.EMBEDDING: "Generating Embeddings",
    JobStage.COMPLETE: "Indexing Complete",
    JobStage.FAILED: "Failed",
}

# Document-level status implied by each job stage, so the two never drift
# apart - every place that advances a job's stage also sets the document's
# training_status to the matching value from this table.
JOB_STAGE_TO_DOCUMENT_STATUS: dict[JobStage, DocumentTrainingStatus] = {
    JobStage.QUEUED: DocumentTrainingStatus.QUEUED,
    JobStage.PARSING: DocumentTrainingStatus.PARSING,
    JobStage.TAGGING: DocumentTrainingStatus.TAGGING,
    JobStage.EMBEDDING: DocumentTrainingStatus.EMBEDDING,
    JobStage.COMPLETE: DocumentTrainingStatus.INDEXED,
    JobStage.FAILED: DocumentTrainingStatus.FAILED,
}


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
    """TN-MTC-03 confidence thresholds. Kept verbatim in sync with
    app/tasks/tender_pipeline.py's AUTO_MATCH_THRESHOLD / SUGGESTED_MATCH_FLOOR —
    update both together."""

    AUTO = "auto"          # confidence >= 0.85
    SUGGESTED = "suggested"  # 0.60 - 0.84
    MISSING = "missing"     # < 0.60


class MatchReviewStatus(str, enum.Enum):
    """TN-MTC-05 - manager/user review of a suggested match."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REASSIGNED = "reassigned"


class UsagePurpose(str, enum.Enum):
    """What an Anthropic API call was actually for - the one thing a raw
    token count can't tell you on its own. Every LlmUsageEvent row is tagged
    with exactly one of these, so cost can be sliced by "why", not just
    "how much": a tender that costs more than expected is either genuinely
    long or its extraction is misconfigured, and this is what tells the two
    apart.

    TENDER_EXTRACTION - one row per chunk, app/services/extraction.py's
      extract_chunk(), the high-volume mechanical call.
    TENDER_METADATA - one row per tender, extract_tender_metadata()'s single
      pass over the opening pages.
    LIBRARY_TAGGING - app/services/library/metadata.py's auto-tagging call
      when a heuristic leaves a metadata field blank.
    LIBRARY_ASK - the Evidence Library's grounded Ask
      (app/services/library/rag.py), the one call site that uses the
      heavier ANTHROPIC_MODEL rather than the cheap extraction tier.
    """

    TENDER_EXTRACTION = "tender_extraction"
    TENDER_METADATA = "tender_metadata"
    LIBRARY_TAGGING = "library_tagging"
    LIBRARY_ASK = "library_ask"
