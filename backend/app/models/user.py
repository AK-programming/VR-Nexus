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

from sqlalchemy import ARRAY, JSON, Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import UserRole


class User(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), nullable=False, default=UserRole.USER
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Email verification ---
    # NULL means "not verified yet" - the account exists but /api/auth/login
    # refuses it until this is set. Set the moment the emailed confirmation
    # link is redeemed (POST /api/auth/verify-email), or immediately at
    # registration when SMTP isn't configured on this deployment (there is no
    # way to ever prove an address without sending mail, so enforcing
    # verification with no working mailer would just brick every account -
    # see register()'s own comment in api/routes/auth.py). A timestamp rather
    # than a bool so "when" is on hand for free without a second column.
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Per-feature access grants for a USER row - see FeatureKey's docstring.
    # An ADMIN row's list is never read (require_feature always admits an
    # admin), so it is left empty rather than populated with every key.
    # Stored as a Postgres text array so a new feature key never needs a
    # migration of its own, only a new FeatureKey member.
    feature_access: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=list, server_default="{}"
    )

    # --- AUTH-06: account lockout after 5 consecutive failed logins ---
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Excel export customization (client requirement, Users admin follow-up) ---
    # The user's own reusable default export shape for the generated
    # Requirements tracker (column show/hide/order/rename, delete-empty-rows,
    # user-added blank columns) - see app/schemas/excel_template.ExcelTemplate
    # for the JSON shape and app/tasks/tender_pipeline._resolve_excel_template
    # for how it's applied. Null means "use the platform default layout",
    # which is what every account has until it opens the customizer.
    default_excel_template: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

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
