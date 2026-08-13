"""Chat client for parsing fallback and metadata auto-tagging.

Points at AgentRouter (OpenAI-compatible). Every call site must tolerate a
None/empty return: the LLM is an enhancement, not a dependency. With
LLM_ENABLED=false the whole pipeline still runs on heuristics alone.
"""
import json
import logging
import re

from app.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        # AgentRouter allowlists client User-Agents and rejects the SDK default
        # ("OpenAI/Python x.y.z") with 401 unauthorized_client_error.
        _client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            default_headers={"User-Agent": settings.OPENAI_USER_AGENT},
        )
    return _client


def is_available() -> bool:
    return settings.llm_available


def complete(prompt: str, system: str = "", max_tokens: int = 2000) -> str:
    """Single-turn completion. Returns "" on any failure rather than raising —
    callers fall back to heuristics.

    No `temperature`: the newer Claude models reject it outright (400
    "`temperature` is deprecated for this model"), and their default is already
    low enough for extraction work. Determinism here comes from asking for
    specific fields, not from the sampler.
    """
    if not is_available():
        return ""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = _get_client().chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as exc:
        logger.warning("LLM call failed, falling back to heuristics: %s", exc)
        return ""


def complete_json(prompt: str, system: str = "", max_tokens: int = 2000) -> dict:
    """Completion expected to return a JSON object. Returns {} on failure."""
    raw = complete(prompt, system=system, max_tokens=max_tokens)
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
