"""
Importing this package pulls in every model class, which registers them on
Base.metadata. Alembic's env.py imports this module so `alembic revision
--autogenerate` can see every table, and nothing gets silently skipped just
because its file was never imported elsewhere.
"""
from app.models.base import Base  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.document import Document, DocumentImage  # noqa: F401
from app.models.chunk import Chunk  # noqa: F401
from app.models.tender import Tender  # noqa: F401
from app.models.requirement import Requirement, RequirementEvidenceMatch  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401

__all__ = [
    "Base",
    "User",
    "Document",
    "DocumentImage",
    "Chunk",
    "Tender",
    "Requirement",
    "RequirementEvidenceMatch",
    "AuditLog",
]
