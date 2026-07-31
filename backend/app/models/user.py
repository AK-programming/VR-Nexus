"""
Task 1.1.1 - User model
Linked requirements: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06

Covers registration fields, the RBAC role field, and the account-lockout
fields needed by AUTH-06 (15 min lock after 5 failed attempts). The actual
endpoints (register/login/refresh/lockout logic) are Task 1.2, built on top
of this table.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import UserRole


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False, default=UserRole.USER
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- AUTH-06: account lockout after 5 consecutive failed logins ---
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- relationships ---
    uploaded_documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        back_populates="uploaded_by_user", foreign_keys="Document.uploaded_by"
    )
    uploaded_tenders: Mapped[list["Tender"]] = relationship(  # noqa: F821
        back_populates="uploaded_by_user", foreign_keys="Tender.uploaded_by"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        back_populates="user", foreign_keys="AuditLog.user_id"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role.value}>"
