"""Single-use redemption tracking for email verification tokens.

Same mechanism as services/password_reset_tokens.py, for the same reason -
see that file's docstring in full. Short version: create_email_verification_token
(app/core/security.py) mints a signed JWT that proves *who* a confirmation is
for, but a JWT alone is a reusable bearer proof, and a verification link that
travels over email can sit in an inbox or get opened twice. This makes each
token's `jti` claimable exactly once.

Kept as its own tiny module rather than generalizing password_reset_tokens.py
to take a namespace - duplicating five lines is cheaper than the confusion of
one module serving two unrelated token kinds under a name that only mentions
one of them (the same call account_email.py's docstring makes for not sharing
its SMTP-send code with support_email.py).
"""
from __future__ import annotations

from typing import Optional

import redis

from app.core.config import get_settings

_KEY_PREFIX = "email-verification-redeemed:"

_redis_client: Optional[redis.Redis] = None


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def redeem(jti: str, ttl_seconds: int) -> bool:
    """Atomically claim `jti` as redeemed. Returns True the first time this is
    called for a given jti, False on every call after - see
    password_reset_tokens.redeem's docstring for the full reasoning, which
    applies here unchanged."""
    return bool(_redis().set(_KEY_PREFIX + jti, "1", nx=True, ex=max(ttl_seconds, 1)))
