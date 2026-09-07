"""Single-use redemption tracking for password reset tokens.

`create_password_reset_token` mints a signed JWT (see app/core/security.py) that
proves *who* a reset is for, but a JWT on its own is only ever a bearer proof:
anyone holding an unexpired copy can redeem it, as many times as they like,
until it expires. That is fine for an access token, which is meant to be
reused for 24h. It is not fine for a reset link: it travels over email (a
channel this app does not control the security of) and often sits in an inbox,
a "Sent" folder, or a scanning/prefetching mail client for the rest of its
30-minute life - if that link leaks or gets clicked twice, a still-valid token
should not be a still-usable one.

This module makes each token's `jti` (a random id minted alongside it, carried
in the JWT payload) usable exactly once. Redis is the natural place for that:
it is already provisioned (Celery, the two progress sockets' ws_tickets), and
a "mark used" that must be atomic across concurrent requests is exactly what
it's for.
"""
from __future__ import annotations

from typing import Optional

import redis

from app.core.config import get_settings

_KEY_PREFIX = "password-reset-redeemed:"

_redis_client: Optional[redis.Redis] = None


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def redeem(jti: str, ttl_seconds: int) -> bool:
    """Atomically claim `jti` as redeemed. Returns True the first time this is
    called for a given jti, False on every call after (including a second,
    near-simultaneous request racing the first) - so the caller can proceed
    only on True and must treat False exactly like an invalid token.

    `SET ... NX` is what makes this safe under a race: it sets the key only if
    it does not already exist, and does the check-and-set in one atomic Redis
    operation, so two requests redeeming the same token at the same instant
    cannot both see "not yet redeemed".

    `ttl_seconds` should be the token's own remaining lifetime (or a little
    more): once the JWT itself has expired, decode_token() rejects it anyway,
    so there is no reason for the redeemed-marker to outlive it in Redis.
    """
    return bool(_redis().set(_KEY_PREFIX + jti, "1", nx=True, ex=max(ttl_seconds, 1)))
