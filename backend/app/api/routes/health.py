"""Health probes — /api/health/llm.

Purpose: answer "why is extraction failing?" without having to re-run a full
tender and read the worker log. The probe hits Anthropic through the exact
URL, authorization header and request shape `services/extraction.py` uses
(same `AsyncOpenAI` client, same base URL, same model), so its reply is the
same reply an extraction chunk would get. If the key is rejected, the model is
retired, the network is blocked, or the quota is spent, the operator sees the
underlying HTTP error verbatim rather than a downstream "0 requirements
extracted" mystery.

Auth: requires a signed-in user. The endpoint reveals the configured model name
and base URL, which are not secrets but are configuration, so it stays behind
the same JWT gate as the rest of the API rather than being publicly probeable.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from openai import APIStatusError

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.models.user import User
from app.services.extraction import _get_client  # same client the pipeline uses

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/llm")
async def check_llm(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Round-trip one tiny prompt to the configured LLM.

    Returns 200 with `{ok: true}` on success and 200 with `{ok: false, error: ...}`
    on failure — never a 5xx. The distinction is: "the probe RAN" (200, with a
    result) vs. "the probe crashed" (5xx). Reading the failure IS the point;
    surfacing it as a 5xx would mean the caller has to inspect the response body
    twice as many ways to learn one fact.
    """
    settings = get_settings()
    started = time.monotonic()

    payload = {
        "model": settings.ANTHROPIC_MODEL,
        "base_url": settings.ANTHROPIC_BASE_URL,
    }

    if not settings.LLM_ENABLED:
        return {
            "ok": False,
            **payload,
            "error": "LLM_ENABLED=false in the environment. Extraction will not run.",
        }
    if not settings.ANTHROPIC_API_KEY:
        return {
            "ok": False,
            **payload,
            "error": "ANTHROPIC_API_KEY is empty. Set it in backend/.env.",
        }

    try:
        client = _get_client()
        # Deliberately trivial: we care about the round-trip, not the answer.
        # A 12-second bound so a hung network cannot leave this endpoint waiting.
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.ANTHROPIC_MODEL,
                max_tokens=8,
                messages=[
                    {"role": "user", "content": "Reply with the single word: pong"},
                ],
            ),
            timeout=12.0,
        )
        content = (response.choices[0].message.content or "").strip()
        return {
            "ok": True,
            **payload,
            "reply": content,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except APIStatusError as exc:
        # The one path where the caller learns the useful bit: HTTP status + body.
        # A 404 is a retired model, a 401/403 is a rejected key, a 429 is quota.
        body = ""
        try:
            body = exc.response.text[:1200] if exc.response is not None else ""
        except Exception:  # noqa: BLE001 - already reporting a failure
            body = ""
        return {
            "ok": False,
            **payload,
            "status": exc.status_code,
            "error": f"{type(exc).__name__}: {exc}",
            "response_body": body,
        }
    except asyncio.TimeoutError:
        return {
            "ok": False,
            **payload,
            "error": "The LLM did not respond within 12 seconds. The worker's network may be blocked from api.anthropic.com.",
        }
    except Exception as exc:  # noqa: BLE001 - the whole point is to surface it
        logger.exception("LLM health probe failed")
        return {
            "ok": False,
            **payload,
            "error": f"{type(exc).__name__}: {exc}",
        }
