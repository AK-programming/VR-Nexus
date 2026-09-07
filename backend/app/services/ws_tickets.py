"""Short-lived, single-use tickets for the two progress WebSockets.

A WebSocket can't carry an `Authorization` header the way a normal fetch()
can (see ws.py's own docstring for why), so both progress sockets used to
take the real access token as a `?token=` query parameter instead. That
worked, but it meant a long-lived (24h) bearer credential sat in every proxy
access log, browser history entry and Referer header for as long as that
token stayed valid - a much bigger leak surface than the few seconds the
socket actually needs it for.

A ticket is the standard fix for exactly this shape of problem: mint a
random, single-use, short-lived value over an ordinary authenticated HTTP
call (one that CAN carry a real Authorization header, and whose logs matter
far less than a URL that lands in browser history), then hand that ticket -
never the access token - to the WebSocket. Redeeming it consumes it
atomically, so a ticket that leaks anywhere is worthless within a minute at
most and cannot be replayed even once, let alone for a whole session.

Deliberately its own module rather than folded into services/progress.py or
services/library/library_progress.py: those two are about the two pipelines'
progress payloads, this is about authenticating the connection itself, and
both sockets share this one regardless of which pipeline they belong to.
"""
from __future__ import annotations

import json
import secrets
import uuid
from typing import Optional

import redis

from app.core.config import get_settings

#: How long a minted ticket stays redeemable. Long enough to cover opening
#: the WebSocket right after the HTTP call that minted it (well under a
#: second in practice); short enough that a ticket sitting in a log is stale
#: before anyone could act on it.
TICKET_TTL_SECONDS = 60

_KEY_PREFIX = "ws-ticket:"

_redis_client: Optional[redis.Redis] = None


def _redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def issue_ticket(user_id: uuid.UUID, scope: str, resource_id: str) -> str:
    """Mint a ticket good for one WebSocket connection to (scope, resource_id).

    Called from an authenticated HTTP route, so the caller's identity is
    already established the normal way (Authorization header, checked by
    get_current_user) before this ever runs - the ticket just carries that
    already-verified identity forward to a connection type that can't verify
    it itself.

    `scope` and `resource_id` are bound into the ticket so it is good for
    exactly the one tender or library job it was requested for, not a
    passe-partout a client could point at a different id.
    """
    ticket = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"user_id": str(user_id), "scope": scope, "resource_id": resource_id}
    )
    _redis().set(_KEY_PREFIX + ticket, payload, ex=TICKET_TTL_SECONDS)
    return ticket


def redeem_ticket(ticket: str, scope: str, resource_id: str) -> Optional[uuid.UUID]:
    """Consume a ticket and return the user id it was issued to, or None if
    it's missing, expired, already used, or scoped to a different (scope,
    resource_id) than the one being connected to.

    GETDEL, not GET-then-DELETE: a WebSocket handshake is exactly the kind of
    thing a client can retry or double-fire (a React effect re-running, a
    reconnect racing the first attempt), and a plain GET would let two
    near-simultaneous attempts both succeed off the same ticket. GETDEL reads
    and removes the key in one atomic server-side operation, so only the
    first redemption can ever win - the second sees nothing, exactly as if
    the ticket had never existed.
    """
    raw = _redis().getdel(_KEY_PREFIX + ticket)
    if raw is None:
        return None

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if data.get("scope") != scope or data.get("resource_id") != resource_id:
        return None

    try:
        return uuid.UUID(data["user_id"])
    except (KeyError, TypeError, ValueError):
        return None
