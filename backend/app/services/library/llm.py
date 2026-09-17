"""Chat client for parsing fallback and metadata auto-tagging.

Talks to an LLM through an OpenAI-compatible endpoint using the `openai`
client library — the library is just the HTTP/SDK plumbing; which provider
it's pointed at (Anthropic, OpenAI, or Google Gemini - all three publish an
OpenAI-compatible endpoint) is chosen per task in Settings, see
app/services/app_settings.py's PROVIDERS / MODEL_TASKS. Every call site must
tolerate a None/empty return: the LLM is an enhancement, not a dependency.
With no key configured for the resolved provider (or `LLM_ENABLED=false`)
the whole pipeline still runs on heuristics alone.

Deliberate deviation from the source copy of this module: it set a
`default_headers={"User-Agent": ...}` override in order to send
`claude-cli/1.0.60 (external, cli)` — i.e. to impersonate Anthropic's own
first-party CLI, because the third-party router it pointed at allowlists
client User-Agents and rejects the SDK default with a 401. That impersonation
is not reproduced here: talking to a provider's own API directly means there
is no reseller allowlist to satisfy, so the SDK sends its own honest
User-Agent unless `ANTHROPIC_USER_AGENT` is explicitly set to override it
(Anthropic only - see `_get_client` below).
"""
import json
import logging
import re
import time
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import UsagePurpose

_settings = get_settings()

logger = logging.getLogger(__name__)

#: One cached client per provider - see extraction.py's `_clients` for the
#: same shape and the same reason (an admin can point this module's calls at
#: any of app_settings.PROVIDERS now, not just Anthropic).
_clients: dict[str, "OpenAI"] = {}  # noqa: F821 - OpenAI imported lazily in _get_client
#: See extraction.py's `_client_generation` - same pattern, same reason: an
#: admin-saved API key change for ANY provider (app/services/app_settings.py)
#: must take effect on this module's next call, not after a restart.
_client_generation: int = -1


def _get_client(provider: str = "anthropic"):
    global _clients, _client_generation
    from app.services.app_settings import get_effective_api_key, key_generation, provider_base_url

    generation = key_generation()
    if generation != _client_generation:
        _clients = {}
        _client_generation = generation

    if provider not in _clients:
        from openai import OpenAI

        kwargs = dict(
            api_key=get_effective_api_key(provider),
            base_url=provider_base_url(provider),
        )
        # Anthropic-only override - see module docstring.
        if provider == "anthropic" and _settings.ANTHROPIC_USER_AGENT:
            kwargs["default_headers"] = {"User-Agent": _settings.ANTHROPIC_USER_AGENT}
        _clients[provider] = OpenAI(**kwargs)
    return _clients[provider]


def extraction_model() -> dict[str, str]:
    """The `{"provider", "model"}` for mechanical, high-volume calls -
    library auto-tagging here, tender extraction in services/extraction.py.
    Resolved through app_settings so an admin's Settings-screen choice
    (app/services/app_settings.py's MODEL_TASKS, task "extraction") takes
    effect on the very next call, falling back to config.py's
    ANTHROPIC_EXTRACTION_MODEL (provider "anthropic") when no override is
    set. Call sites here used to read _settings.ANTHROPIC_EXTRACTION_MODEL
    directly."""
    from app.services.app_settings import get_effective_model

    return get_effective_model("extraction")


def reasoning_model() -> dict[str, str]:
    """The `{"provider", "model"}` for the app's one "weighs evidence,
    writes prose" call - the Evidence Library's grounded Ask
    (services/library/rag.py). Same app_settings resolution as
    extraction_model() above, task "reasoning", falling back to config.py's
    ANTHROPIC_MODEL (provider "anthropic")."""
    from app.services.app_settings import get_effective_model

    return get_effective_model("reasoning")


def is_available(provider: str = "anthropic") -> bool:
    """True when the app has *some* working key for `provider` - a DB
    override (Settings) or that provider's .env key - and LLM_ENABLED isn't
    false. Checks the DB override (not just settings.llm_available) so an
    admin who set a key only in Settings, with .env left blank, is still
    "available". Defaults to "anthropic" for callers that check availability
    before knowing which task/provider they'll actually use.
    """
    if not _settings.LLM_ENABLED:
        return False
    from app.services.app_settings import get_effective_api_key

    return bool(get_effective_api_key(provider))


def complete(
    prompt: str,
    system: str = "",
    max_tokens: int = 2000,
    model: Optional[dict[str, str]] = None,
    *,
    db: Optional[Session] = None,
    purpose: Optional[UsagePurpose] = None,
    document_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> str:
    """Single-turn completion. Returns "" on any failure rather than raising —
    callers fall back to heuristics.

    `model` is a `{"provider", "model"}` pair (app_settings.get_effective_model's
    return shape) and defaults to reasoning_model() (used for the grounded
    Ask). Pass extraction_model() explicitly for mechanical, high-volume
    calls like auto-tagging, the same tiering app/services/extraction.py
    uses for tender extraction — cheaper model, since there is no judgment
    call in "copy this text into this field". Both resolve through
    app_settings, so an admin's Settings-screen choice (including a
    different provider, not just a different Anthropic model) applies
    immediately rather than needing a restart (see extraction_model /
    reasoning_model above).

    No `temperature`: some newer models reject it outright (400 "`temperature`
    is deprecated for this model"), and their default is already low enough for
    extraction work. Determinism here comes from asking for specific fields, not
    from the sampler.

    `db`/`purpose`/`document_id`/`user_id` are optional and all keyword-only:
    when `db` and `purpose` are both given, this call is recorded to the
    llm_usage_events table (see services/usage_tracking.py) with attribution
    to whichever of `document_id`/`user_id` the caller has in scope. Both
    call sites through this function (library auto-tagging via
    complete_json(), and the Evidence Library's grounded Ask) pass these.
    """
    resolved = model or reasoning_model()
    if not is_available(resolved["provider"]):
        return ""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    started = time.monotonic()
    try:
        response = _get_client(resolved["provider"]).chat.completions.create(
            model=resolved["model"],
            messages=messages,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        if db is not None and purpose is not None:
            usage = response.usage
            from app.services.usage_tracking import record_usage

            record_usage(
                db,
                model=resolved["model"],
                purpose=purpose,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                latency_ms=latency_ms,
                document_id=document_id,
                user_id=user_id,
            )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM call failed, falling back to heuristics: %s", exc)
        return ""


def complete_json(
    prompt: str,
    system: str = "",
    max_tokens: int = 2000,
    model: Optional[dict[str, str]] = None,
    *,
    db: Optional[Session] = None,
    purpose: Optional[UsagePurpose] = None,
    document_id: Optional[uuid.UUID] = None,
    user_id: Optional[uuid.UUID] = None,
) -> dict:
    """Completion expected to return a JSON object. Returns {} on failure."""
    raw = complete(
        prompt,
        system=system,
        max_tokens=max_tokens,
        model=model,
        db=db,
        purpose=purpose,
        document_id=document_id,
        user_id=user_id,
    )
    if not raw:
        return {}

    parsed = _extract_json(raw)
    if parsed is None:
        logger.warning("LLM returned unparseable JSON: %s", raw[:200])
        return {}
    return parsed


def _extract_json(text: str) -> dict | None:
    """Pull a JSON object out of a response that may be fenced or prefixed."""
    text = text.strip()

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)

    try:
        result = json.loads(text)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            result = json.loads(text[start : end + 1])
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None
    return None
