"""
Runtime-editable application settings — an admin can change these without a
`.env` edit and a container restart: the API key for each LLM provider this
app can call (Anthropic, OpenAI, Gemini), which provider/model each task
uses, and per-model pricing overrides.

This is a SINGLETON table: exactly one row exists, fetched (and created on
first use) by app/services/app_settings.py's `_get_or_create_row`. A
key-value table would also work, but a single fixed-shape row is simpler to
reason about for two settings that always travel together and are both
admin-only, and it makes "no override yet" trivially representable as a
freshly-created row with both columns null/empty rather than a missing key
that every reader has to special-case.

Why this needs to exist at all: before this, ANTHROPIC_API_KEY and
ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS lived only in core/config.py,
read once from .env at process start via `@lru_cache`. Rotating a leaked
or expired key meant editing .env and restarting every worker - the user's
own stated concern ("if the api key expire or exploid so it a big issue").
A row here, when present, takes precedence over the .env value; see
app_settings.py's `get_effective_api_key` / `get_effective_pricing_table`
for exactly how the two are merged, and extraction.py / library/llm.py for
how a changed key invalidates the cached LLM client without a restart.

The key is stored encrypted (Fernet, keyed from JWT_SECRET_KEY - see
app_settings.py) rather than in plaintext, since this table is otherwise a
plain Postgres row an ordinary DB backup or read replica can see.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class AppSettings(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "app_settings"

    #: Fernet-encrypted Anthropic API key, or NULL when no override has ever
    #: been set (in which case the app falls back to ANTHROPIC_API_KEY from
    #: .env - see app_settings.get_effective_api_key).
    anthropic_api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Same idea, for OpenAI and Gemini - added per a later client follow-up
    #: ("able to change the api to gemini or openai"). NULL falls back to
    #: OPENAI_API_KEY / GEMINI_API_KEY from .env, same as the Anthropic key.
    #: One column per provider rather than a JSON blob, so each key gets its
    #: own Fernet-encrypted column the same way the Anthropic key already
    #: does, instead of a shape that's encrypted differently from the others.
    openai_api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gemini_api_key_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    #: Partial override of ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS, e.g.
    #: {"claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0}}. Merged
    #: OVER config.py's static table (this table's entries win per model id;
    #: a model id not present here still falls back to config.py, so a model
    #: added to config.py later is never silently missing here) - see
    #: app_settings.get_effective_pricing_table.
    pricing_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    #: Per-task model + provider overrides, e.g.
    #: {"extraction": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    #:  "reasoning": {"provider": "openai", "model": "gpt-4o"}}. A task key
    #: missing here falls back to its config.py default, always on the
    #: "anthropic" provider (ANTHROPIC_EXTRACTION_MODEL / ANTHROPIC_MODEL) -
    #: same "override wins per key, default fills the rest" shape as
    #: pricing_overrides above. Originally just a bare model-id string per
    #: task (Anthropic-only); widened to {"provider","model"} per a later
    #: client follow-up ("able to change the api to gemini or openai... they
    #: select the model for specific use") - app_settings.get_effective_model
    #: still accepts a bare string here for a row saved before that change.
    model_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    #: When the pricing table was last (attempted to be) auto-refreshed from
    #: Anthropic's own pricing page, and what happened - shown on the admin
    #: settings screen so "Refresh" never looks like a silent no-op. Free text
    #: rather than a separate log table: this is a UI convenience, not an
    #: audit trail (AuditLog already covers user-facing account changes).
    last_pricing_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_pricing_refresh_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
