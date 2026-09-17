"""
Effective-value lookups for the runtime-editable settings (a per-provider
API key, per-task provider+model selection, per-model pricing) plus the
admin actions that change them.

Why this module exists: core/config.py's Settings is read once from .env at
process start and cached forever (`@lru_cache`). That is fine for values
that only ever change at deploy time, but the user's explicit ask was to be
able to rotate the Anthropic API key ("if the api key expire or exploid so
it a big issue") and refresh pricing without editing .env and restarting
every worker - later extended to letting an admin switch a task onto a
different provider entirely ("if the user will change the api to gemini or
openai etc they will enter their api key and select the model"). This
module is the layer that makes a DB-stored override take effect
immediately:

  - get_effective_api_key(provider) / get_effective_pricing_table() are what
    every caller should use instead of reading settings.ANTHROPIC_API_KEY /
    settings.ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS directly. Both check
    the app_settings row first and fall back to the .env-sourced default.
  - key_generation() is a plain in-process counter, bumped by set_api_key()
    or clear_api_key() for ANY provider. extraction.py's and
    library/llm.py's `_get_client()` each stash the generation they built
    their cached clients from, and rebuild whichever client they need the
    next time they are called if the generation has moved on. This is
    deliberately NOT a DB-backed signal (no polling, no extra query per LLM
    call) - it only has to work within one running process, same as the
    client caches themselves, and every worker picks up a changed key the
    moment it next handles a call after the admin saves it. One counter for
    all three providers rather than one each: simpler, and a key change is
    rare enough that rebuilding every provider's cached client on any one
    of them changing costs nothing worth optimising away.

Every API key is stored encrypted at rest (Fernet) rather than in
plaintext, since app_settings is an ordinary Postgres row visible to
anything with database access (backups, read replicas, an admin's
`SELECT *`). The Fernet key is derived from JWT_SECRET_KEY via SHA-256
rather than requiring a brand-new secret in .env - this app already treats
JWT_SECRET_KEY as the one value that must stay private, and rotating it
would also rotate every signed-in session, so reusing it here adds no new
secret-management burden.
"""
import base64
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.app_setting import AppSettings

logger = logging.getLogger(__name__)

_settings = get_settings()

#: Every provider this app can call. Not user-editable beyond these three -
#: a new provider needs real client code (base_url, auth shape) added below
#: and in extraction.py / library/llm.py before it could do anything, so
#: this stays a fixed tuple rather than a free-form value.
PROVIDERS = ("anthropic", "openai", "gemini")

PROVIDER_LABELS = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "gemini": "Google Gemini",
}

#: Which AppSettings column holds each provider's encrypted key.
_KEY_FIELD = {
    "anthropic": "anthropic_api_key_encrypted",
    "openai": "openai_api_key_encrypted",
    "gemini": "gemini_api_key_encrypted",
}

#: The .env-sourced key/base_url for each provider, read once at import time
#: the same way _settings itself is. OpenAI and Gemini both publish an
#: OpenAI-compatible endpoint (see core/config.py), so every provider here
#: is reachable through the one `openai` client library this app already
#: depends on - no per-provider SDK.
_ENV_KEY = {
    "anthropic": lambda: _settings.ANTHROPIC_API_KEY,
    "openai": lambda: _settings.OPENAI_API_KEY,
    "gemini": lambda: _settings.GEMINI_API_KEY,
}
_BASE_URL = {
    "anthropic": lambda: _settings.ANTHROPIC_BASE_URL,
    "openai": lambda: _settings.OPENAI_BASE_URL,
    "gemini": lambda: _settings.GEMINI_BASE_URL,
}


def _require_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'.")


def provider_base_url(provider: str) -> str:
    """The base_url the client for this provider should point at - always
    the .env value; unlike the key, this isn't something Settings lets an
    admin override at runtime, since a provider's API endpoint isn't
    something that rotates the way a leaked key does."""
    _require_provider(provider)
    return _BASE_URL[provider]()


# Bumped by set_api_key()/clear_api_key() for any provider; read by
# extraction.py / library/llm.py to decide whether their cached client(s)
# are stale. Starts at 0 so a process that never touches Settings never
# rebuilds a client it didn't need to.
_key_generation = 0


def key_generation() -> int:
    return _key_generation


def _bump_key_generation() -> None:
    global _key_generation
    _key_generation += 1


def _fernet() -> Fernet:
    digest = hashlib.sha256(_settings.JWT_SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # JWT_SECRET_KEY changed since this row was written, or the column was
        # edited by hand. Treated the same as "no override stored" rather than
        # a crash - the .env key is still a working fallback.
        logger.warning(
            "Could not decrypt a stored API key (JWT_SECRET_KEY may have changed) - "
            "falling back to the .env-sourced key for that provider."
        )
        return ""


def _get_or_create_row(db: Session) -> AppSettings:
    row = db.query(AppSettings).order_by(AppSettings.created_at.asc()).first()
    if row is None:
        row = AppSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_row(db: Session) -> AppSettings:
    """The one app_settings row, for read-only display (masked key, current
    overrides, last refresh info). Creates it on first call."""
    return _get_or_create_row(db)


def provider_key_status(provider: str, db: Session) -> dict:
    """`{"configured", "source", "masked"}` for one provider's key - the
    Settings screen's only view into whether a key exists and where it came
    from; the real key value never leaves get_effective_api_key(). `source`
    is "settings" (a DB override is set), "env" (falling back to .env), or
    "none" (neither)."""
    _require_provider(provider)
    row = _get_or_create_row(db)
    encrypted = getattr(row, _KEY_FIELD[provider])
    env_key = _ENV_KEY[provider]()
    if encrypted:
        source = "settings"
        effective_key = get_effective_api_key(provider, db)
    elif env_key:
        source = "env"
        effective_key = env_key
    else:
        source = "none"
        effective_key = ""
    return {
        "configured": bool(effective_key),
        "source": source,
        "masked": mask_api_key(effective_key),
    }


def mask_api_key(key: str) -> str:
    """`sk-ant-api03-...9f2a` - enough for an admin to recognise which key is
    active without the full value ever round-tripping back to the browser."""
    if not key:
        return ""
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:8]}...{key[-4:]}"


def get_effective_api_key(provider: str = "anthropic", db: Optional[Session] = None) -> str:
    """The key every LLM call site should use for this provider: a DB
    override if one has been set, otherwise that provider's .env-sourced
    key. Opens its own short-lived session when the caller has none in
    scope (extraction.py's and library/llm.py's `_get_client()` are called
    from contexts that do not always have a `db` handy), rather than
    forcing a `db` parameter onto call sites that never needed one before
    this feature existed.

    `provider` defaults to "anthropic" so every call site written before
    this app supported more than one provider keeps working unchanged.
    """
    _require_provider(provider)
    owns_session = db is None
    if owns_session:
        from app.core.database import SessionLocal

        db = SessionLocal()
    try:
        row = _get_or_create_row(db)
        encrypted = getattr(row, _KEY_FIELD[provider])
        if encrypted:
            decrypted = _decrypt(encrypted)
            if decrypted:
                return decrypted
        return _ENV_KEY[provider]()
    except Exception:
        # A DB hiccup here must not take LLM calls down - fall back to the
        # .env value, same posture as usage_tracking.record_usage's own
        # never-raise rule.
        logger.exception(
            "Could not read app_settings; using the .env-sourced key for '%s'.", provider
        )
        return _ENV_KEY[provider]()
    finally:
        if owns_session:
            db.close()


def get_effective_pricing_table(db: Optional[Session] = None) -> dict[str, dict[str, float]]:
    """config.py's static ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS, with any
    admin-set overrides merged on top per model id. A model id with no
    override still resolves to the static default, so adding a new model to
    config.py later is never masked by a stale overrides row.
    """
    owns_session = db is None
    if owns_session:
        from app.core.database import SessionLocal

        db = SessionLocal()
    try:
        row = _get_or_create_row(db)
        merged = dict(_settings.ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS)
        if row.pricing_overrides:
            for model_id, rates in row.pricing_overrides.items():
                if isinstance(rates, dict) and "input" in rates and "output" in rates:
                    merged[model_id] = {
                        "input": float(rates["input"]),
                        "output": float(rates["output"]),
                    }
        return merged
    except Exception:
        logger.exception("Could not read app_settings; using the static pricing table from .env.")
        return dict(_settings.ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS)
    finally:
        if owns_session:
            db.close()


def set_api_key(
    db: Session, provider: str, new_key: str, admin_user_id: Optional[uuid.UUID] = None
) -> None:
    """Stores a new shared API key for one provider (encrypted) and
    invalidates every process's cached LLM clients on their next call. Does
    not itself verify the key against the provider - that would cost the
    admin a real API call just to save a settings page, and the very next
    call routed to this provider will surface an auth error immediately if
    the key is bad.
    """
    _require_provider(provider)
    new_key = new_key.strip()
    if not new_key:
        raise ValueError("API key cannot be empty.")

    row = _get_or_create_row(db)
    setattr(row, _KEY_FIELD[provider], _encrypt(new_key))
    db.commit()
    _bump_key_generation()
    logger.info(
        "%s API key updated by admin %s (masked: %s).",
        PROVIDER_LABELS[provider], admin_user_id, mask_api_key(new_key),
    )


def clear_api_key(db: Session, provider: str) -> None:
    """Reverts one provider to its .env-sourced key - for an admin backing
    out of a bad key change without knowing the previous value offhand."""
    _require_provider(provider)
    row = _get_or_create_row(db)
    setattr(row, _KEY_FIELD[provider], None)
    db.commit()
    _bump_key_generation()


#: The two model "slots" this app actually calls, per the cost-tiering split
#: documented in core/config.py (ANTHROPIC_MODEL vs ANTHROPIC_EXTRACTION_MODEL):
#:   - "extraction": mechanical, high-volume calls - tender requirement
#:     extraction and tender-metadata pull (services/extraction.py), plus
#:     Evidence Library auto-tagging (services/library/metadata.py and the
#:     three parsers under services/library/parsers/). All share one model
#:     today (ANTHROPIC_EXTRACTION_MODEL) and one override here.
#:   - "reasoning": the Evidence Library's grounded Ask (services/library/rag.py),
#:     the one call that weighs evidence and writes prose. Defaults to
#:     ANTHROPIC_MODEL.
#: Not user-editable beyond these two keys - a third slot would need a new
#: call site to actually read it, so the set stays in sync with the code by
#: construction rather than by being a free-form dict.
MODEL_TASKS = ("extraction", "reasoning")

#: Each task's default is always on the "anthropic" provider - the app
#: shipped Anthropic-only, so a deployment that has never touched Settings
#: (or a row saved before "provider" existed) keeps calling exactly what it
#: always called.
_TASK_DEFAULTS = {
    "extraction": lambda: {"provider": "anthropic", "model": _settings.ANTHROPIC_EXTRACTION_MODEL},
    "reasoning": lambda: {"provider": "anthropic", "model": _settings.ANTHROPIC_MODEL},
}


def get_effective_model(task: str, db: Optional[Session] = None) -> dict[str, str]:
    """The `{"provider", "model"}` a given task should call right now: an
    admin-set override for that task if one exists, otherwise the config.py
    default (always provider "anthropic"). Same owns-its-own-session
    pattern as get_effective_api_key, for the same reason - extraction.py
    and library/llm.py call this from module-level helpers that do not
    always have a `db` in scope.

    Unlike the API key, a model/provider change needs no client rebuild and
    no generation counter beyond what set_api_key already bumps for key
    rotation: the provider+model are just resolved fresh on each request,
    so the very next call after a save already uses them (a *new*
    provider's client still has to be built the first time it's used, same
    as any cache miss, but that needs no signal from here).

    Backward compatible with a row saved before this task's value was
    widened from a bare model-id string to {"provider","model"}: a string
    override is treated as "anthropic" with that model id.
    """
    if task not in _TASK_DEFAULTS:
        raise ValueError(f"Unknown model task '{task}'.")

    owns_session = db is None
    if owns_session:
        from app.core.database import SessionLocal

        db = SessionLocal()
    try:
        row = _get_or_create_row(db)
        override = (row.model_overrides or {}).get(task)
        if isinstance(override, str) and override.strip():
            return {"provider": "anthropic", "model": override.strip()}
        if (
            isinstance(override, dict)
            and override.get("provider") in PROVIDERS
            and str(override.get("model") or "").strip()
        ):
            return {"provider": override["provider"], "model": str(override["model"]).strip()}
        return _TASK_DEFAULTS[task]()
    except Exception:
        logger.exception("Could not read app_settings; using the .env default model for '%s'.", task)
        return _TASK_DEFAULTS[task]()
    finally:
        if owns_session:
            db.close()


def get_effective_model_overrides(db: Session) -> dict[str, dict[str, str]]:
    """Every task's effective `{"provider","model"}`, override or default -
    what the Settings screen shows as the current selection for each pair
    of dropdowns."""
    return {task: get_effective_model(task, db) for task in MODEL_TASKS}


def set_model_overrides(db: Session, overrides: dict[str, dict[str, str]]) -> None:
    """Replaces the stored per-task provider+model overrides wholesale, same
    full-replacement shape as set_pricing_overrides. A task omitted from
    `overrides` reverts to its config.py default rather than keeping a
    stale prior override - the Settings screen always submits the complete
    set of dropdowns it showed, so "omitted" means the admin picked the
    default option, not that the field was skipped by accident.
    """
    cleaned: dict[str, dict[str, str]] = {}
    for task, selection in overrides.items():
        if task not in _TASK_DEFAULTS:
            raise ValueError(f"Unknown model task '{task}'.")
        if not isinstance(selection, dict):
            raise ValueError(f"Invalid model selection for task '{task}'.")
        provider = str(selection.get("provider") or "").strip()
        model_id = str(selection.get("model") or "").strip()
        if not provider and not model_id:
            continue  # admin left this task on its default - nothing to store
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}' for task '{task}'.")
        if not model_id:
            raise ValueError(f"Model id cannot be empty for task '{task}'.")
        cleaned[task] = {"provider": provider, "model": model_id}

    row = _get_or_create_row(db)
    row.model_overrides = cleaned
    db.commit()


def set_pricing_overrides(db: Session, overrides: dict[str, dict[str, float]]) -> None:
    """Replaces the stored overrides wholesale - the settings screen always
    submits the complete table it showed the admin (defaults merged with any
    prior overrides), so a partial submission can't accidentally drop a
    model id's override the admin didn't mean to touch."""
    cleaned: dict[str, dict[str, float]] = {}
    for model_id, rates in overrides.items():
        if not isinstance(rates, dict):
            continue
        try:
            cleaned[model_id] = {
                "input": float(rates["input"]),
                "output": float(rates["output"]),
            }
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Invalid input/output rate for model '{model_id}'.")

    row = _get_or_create_row(db)
    row.pricing_overrides = cleaned
    db.commit()


@dataclass
class PricingRefreshResult:
    success: bool
    message: str
    updated_models: list[str] = field(default_factory=list)


# Anthropic publishes no pricing API, so this is a best-effort scrape of
# their own public pricing page - not a reliable integration. It looks for
# each model id this app already knows about (the static table's keys, plus
# any the admin has already overridden) somewhere in the page text, then
# looks for the first two "$<number>" amounts following it and treats them
# as input/output USD-per-million-tokens. That pattern is fragile by nature:
# a redesign of the page, a change in units (per-token vs per-million), or a
# layout where input/output aren't the next two dollar figures after the
# model name will all cause this to find nothing (or, in principle, find
# the wrong two numbers) rather than raise. Manual editing on the same
# screen is always the reliable fallback - this is deliberately labelled as
# "best-effort" in the API response and the UI, never as authoritative.
_PRICING_PAGE_URL = "https://www.anthropic.com/pricing"
_DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")


def refresh_pricing_from_anthropic(db: Session) -> PricingRefreshResult:
    """Attempts to fetch current per-token pricing from Anthropic's public
    pricing page and update the stored overrides for any model id it can
    confidently match. Never raises - a fetch/parse failure comes back as
    `success=False` with an explanation, so the admin sees exactly why
    nothing changed instead of a 500.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is already a dependency
        return PricingRefreshResult(False, "httpx is not installed on the server.")

    row = _get_or_create_row(db)
    known_models = set(_settings.ANTHROPIC_PRICING_USD_PER_MILLION_TOKENS.keys())
    if row.pricing_overrides:
        known_models.update(row.pricing_overrides.keys())

    try:
        response = httpx.get(_PRICING_PAGE_URL, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        page_text = response.text
    except Exception as exc:
        result = PricingRefreshResult(
            False,
            f"Could not reach Anthropic's pricing page ({exc.__class__.__name__}). "
            "Edit the table below by hand instead.",
        )
        _record_refresh_attempt(db, row, result)
        return result

    found: dict[str, dict[str, float]] = {}
    for model_id in sorted(known_models):
        idx = page_text.find(model_id)
        if idx == -1:
            continue
        window = page_text[idx : idx + 600]
        amounts = _DOLLAR_RE.findall(window)
        if len(amounts) >= 2:
            try:
                found[model_id] = {"input": float(amounts[0]), "output": float(amounts[1])}
            except ValueError:
                continue

    if not found:
        result = PricingRefreshResult(
            False,
            "Reached Anthropic's pricing page but could not confidently match any "
            "configured model to a price on it (the page layout may not match what "
            "this app looks for). Nothing was changed - edit the table below by hand.",
        )
        _record_refresh_attempt(db, row, result)
        return result

    merged_overrides = dict(row.pricing_overrides or {})
    merged_overrides.update(found)
    row.pricing_overrides = merged_overrides
    result = PricingRefreshResult(
        True,
        f"Updated {len(found)} model price(s) from Anthropic's pricing page. "
        "Double-check the numbers below - this is a best-effort page scrape, "
        "not an official pricing API.",
        updated_models=sorted(found.keys()),
    )
    _record_refresh_attempt(db, row, result)
    return result


def _record_refresh_attempt(db: Session, row: AppSettings, result: PricingRefreshResult) -> None:
    row.last_pricing_refresh_at = datetime.now(timezone.utc)
    row.last_pricing_refresh_result = result.message
    db.commit()
