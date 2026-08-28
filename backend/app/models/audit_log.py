"""
Task 1.1.6 - Audit log model
Linked requirement: AUTH-04 (admin audit trail), and supports 9.3.2 security
testing later.

Deliberately generic (action / resource_type / resource_id / details) so
one table can log every kind of event - logins, tender runs, document
training, user management - instead of a separate table per action type.
`details` holds whatever extra context that specific action needs.
"""
import uuid
from typing import Optional

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class AuditLog(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    # Nullable: some events (failed login with unknown email, system/celery
    # errors) have no authenticated user to attach to.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # --- relationships ---
    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")  # noqa: F821

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r} user_id={self.user_id}>"
