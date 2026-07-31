"""
Shared declarative Base + mixins.

Every model in this package inherits from Base, and most also inherit
UUIDPKMixin and TimestampMixin so we don't repeat the same three columns
in every table definition.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPKMixin:
    """Adds a UUID primary key. Generated client-side (Python), so it does not
    depend on a Postgres extension like pgcrypto being enabled."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Adds created_at / updated_at columns, both timezone-aware and set
    automatically by the database (not by application code, so they stay
    correct no matter which code path writes the row)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )
