"""
Importing this package pulls in every model class, which registers them on
Base.metadata. Alembic's env.py imports this module so `alembic revision
--autogenerate` can see every table, and nothing gets silently skipped just
because its file was never imported elsewhere.
"""
from app.models.base import Base
from app.models.user import User
from app.models.document import Document, DocumentImage
from app.models.chunk import Chunk
from app.models.index_job import IndexJob
from app.models.tender import Tender
from app.models.tender_chunk import TenderChunk
from app.models.requirement import Requirement, RequirementEvidenceMatch
from app.models.audit_log import AuditLog

__all__ = [
    "Base", "User", "Document", "DocumentImage", "Chunk", "IndexJob",
    "Tender", "TenderChunk", "Requirement", "RequirementEvidenceMatch", "AuditLog",
]