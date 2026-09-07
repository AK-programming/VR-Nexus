"""Chat client for parsing fallback and metadata auto-tagging.

Talks to Claude via Anthropic's OpenAI-compatible endpoint (`ANTHROPIC_BASE_URL`,
`ANTHROPIC_MODEL`) using the `openai` client library — the library is just the
HTTP/SDK plumbing; the provider it is pointed at is always Anthropic. Every
call site must tolerate a None/empty return: the LLM is an enhancement, not a
dependency. With no `ANTHROPIC_API_KEY` set (or `LLM_ENABLED=false`) the whole
pipeline still runs on heuristics alone.

Deliberate deviation from the source copy of this module: it set a
`default_headers={"User-Agent": ...}` override in order to send
`claude-cli/1.0.60 (external, cli)` — i.e. to impersonate Anthropic's own
first-party CLI, because the third-party router it pointed at allowlists
client User-Agents and rejects the SDK default with a 401. That impersonation
is not reproduced here: talking to Anthropic directly means there is no
reseller allowlist to satisfy, so the SDK sends its own honest User-Agent
unless `ANTHROPIC_USER_AGENT` is explicitly set to override it (see
`_get_client` below).
"""
import json
import logging
import re

from app.core.config import get_settings

_settings = get_settings()

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        kwargs = dict(
            api_key=_settings.ANTHROPIC_API_KEY,
            base_url=_settings.ANTHROPIC_BASE_URL,
        )
        if _settings.ANTHROPIC_USER_AGENT:
            kwargs["default_headers"] = {"User-Agent": _settings.ANTHROPIC_USER_AGENT}
        _client = OpenAI(**kwargs)
    return _client


def is_available() -> bool:
    return _settings.llm_available


def complete(prompt: str, system: str = "", max_tokens: int = 2000, model: str = "") -> str:
    """Single-turn completion. Returns "" on any failure rather than raising —
    callers fall back to heuristics.

    `model` defaults to ANTHROPIC_MODEL (the reasoning model, used for the
    grounded Ask). Pass ANTHROPIC_EXTRACTION_MODEL explicitly for mechanical,
    high-volume calls like auto-tagging, the same tiering
    app/services/extraction.py uses for tender extraction — same key, cheaper
    model, since there is no judgment call in "copy this text into this field".

    No `temperature`: some newer models reject it outright (400 "`temperature`
    is deprecated for this model"), and their default is already low enough for
    extraction work. Determinism here comes from asking for specific fields, not
    from the sampler.
    """
    if not is_available():
        return ""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = _get_client().chat.completions.create(
            model=model or _settings.ANTHROPIC_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM call failed, falling back to heuristics: %s", exc)
        return ""


def complete_json(prompt: str, system: str = "", max_tokens: int = 2000, model: str = "") -> dict:
    """Completion expected to return a JSON object. Returns {} on failure."""
    raw = complete(prompt, system=system, max_tokens=max_tokens, model=model)
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
