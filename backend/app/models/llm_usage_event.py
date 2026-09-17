"""
API Usage tracking - one row per Anthropic API call, everywhere this app
makes one (tender extraction, tender metadata, library auto-tagging, the
Evidence Library's grounded Ask - see UsagePurpose for the full list).

Deliberately one row per call, not a running aggregate: a tender's 159-chunk
extraction becomes 159 rows rather than one incremented counter, so the
Usage page can slice by model, by purpose, by user, or by day without
needing to have decided which of those groupings mattered in advance. At
this app's actual call volume (a handful of tenders and documents a day,
each a few hundred rows) the table stays small enough that this is not a
real storage cost, and never rolling rows up keeps the by-day chart and the
per-tender total exact rather than an approximation of one.

Every write goes through app/services/usage_tracking.record_usage(), which
is deliberately non-fatal - the same "an enhancement, not a dependency"
rule app/services/library/llm.py's docstring states for the LLM calls
themselves applies here too: a broken usage write must never take down the
actual extraction, tagging, or Ask call it is trying to measure.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPKMixin
from app.models.enums import UsagePurpose


class LlmUsageEvent(Base, UUIDPKMixin):
    __tablename__ = "llm_usage_events"

    # No TimestampMixin here - that mixin also adds updated_at, and a usage
    # event is write-once (nothing about a past API call is ever edited), so
    # only created_at is meaningful. server_default=func.now() (not the
    # mixin's Python-side default) so the timestamp is Postgres's own clock
    # even for a row written from a Celery worker on a different host.
    # Indexed: every summary/timeseries query filters by a date range first.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    model: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # values_callable is required here: SQLAlchemy's default behavior for a
    # PEP-435 Python enum is to send the member's *name* on INSERT (e.g.
    # "LIBRARY_ASK"), not its *value* ("library_ask"). The Postgres
    # `usage_purpose` type this column maps to was created by
    # alembic/versions/b6e1f3a9c247_add_llm_usage_events.py with only the
    # lowercase value strings as valid labels
    # ('tender_extraction'/'tender_metadata'/'library_tagging'/'library_ask'),
    # so every insert without this argument raised
    # "invalid input value for enum usage_purpose" - silently swallowed by
    # record_usage()'s deliberate never-raise except block, which is why the
    # API Usage page stayed at zero even while real, successful, token-
    # spending calls were happening. values_callable makes this column use
    # UsagePurpose's .value on write, matching the enum type's real labels.
    purpose: Mapped[UsagePurpose] = mapped_column(
        Enum(
            UsagePurpose,
            name="usage_purpose",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        index=True,
    )

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    # Numeric, not Float: this is money. 10 digits / 6 decimal places covers
    # any single call at Anthropic's actual per-token rates many times over
    # (a call would need to cost over $9,999 to overflow it).
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)

    # Wall-clock time of the API round-trip, captured with a timer around
    # the client.chat.completions.create() call at each of the four sites -
    # this is latency, not tokens/second throughput, and it is what backs
    # "how long extraction actually spent waiting on Claude" on both the
    # per-tender badge and the admin Usage page.
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Attribution. All three nullable and independently optional: a library
    # Ask call has a user but no tender or document; a tender's extraction
    # calls have a tender (and, through it, a user) but no document; and a
    # call that somehow reaches record_usage with none of them (should not
    # happen, but record_usage never raises on a missing id) still leaves a
    # usable row for the model/purpose/global totals.
    tender_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    document_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<LlmUsageEvent id={self.id} purpose={self.purpose} model={self.model!r} "
            f"tokens={self.input_tokens}+{self.output_tokens} cost=${self.estimated_cost_usd}>"
        )
