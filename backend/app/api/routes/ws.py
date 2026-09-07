"""
Task 7.1.1 - WebSocket streaming during tender processing
Task 7.1.4 - Resume/reconnect handling
Linked requirements: TRK-01, TRK-04

WebSockets can't carry the "Authorization: Bearer <token>" header the way
a normal fetch() can (browsers don't expose custom headers on the
WebSocket constructor), so a credential still has to travel as a query
param: /ws/tenders/{id}/progress?ticket=<ticket>. It used to be the real
24h access token, but that put a long-lived bearer credential in browser
history and every proxy access log for as long as it stayed valid. Now
it's a short-lived, single-use ticket minted a moment earlier over
POST /api/tenders/{id}/ws-ticket (an ordinary authenticated fetch(), which
CAN carry a real Authorization header) and redeemed exactly once here via
app.services.ws_tickets.redeem_ticket. See that module for the full
rationale.

TRK-04 (resume/reconnect): the moment a client connects - whether this is
the very first connection or a reconnect after the tab was closed for ten
minutes - they're sent the latest known progress immediately, read from
Redis (see app.services.progress.get_latest_progress), before waiting on
any new event. Progress is never lost between the tender's actual work
and a client happening to be listening.

Note on the two progress sockets: this is the tender-side stream. The
Evidence Library has its own at /ws/library/{job_id} (see library_ws.py),
which replays from the persisted index_jobs row rather than from Redis
because its work happens in a Celery worker process. They are deliberately
separate endpoints - different auth shape, different payload, different
lifecycle - and neither should be folded into the other.
"""
import asyncio
import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.enums import TenderStatus
from app.models.tender import Tender
from app.services.progress import get_latest_progress
from app.services.ws_tickets import redeem_ticket

router = APIRouter(tags=["progress"])

_TERMINAL_STATUSES = {TenderStatus.FINALIZED.value, TenderStatus.FAILED.value}


def _authenticate(tender_id: str, ticket: str | None) -> uuid.UUID | None:
    """Redeem a ws-ticket scoped to this tender, returning the user id it was
    issued to (or None if it's missing, expired, already used, or minted for
    a different tender). Redemption is single-use - a second attempt with the
    same ticket, even from the same client retrying, gets None."""
    if not ticket:
        return None
    return redeem_ticket(ticket, "tender", tender_id)


@router.websocket("/ws/tenders/{tender_id}/progress")
async def tender_progress_ws(websocket: WebSocket, tender_id: str, ticket: str | None = None):
    user_id = _authenticate(tender_id, ticket)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing ticket")
        return

    try:
        tender_uuid = uuid.UUID(tender_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid tender id")
        return

    db = SessionLocal()
    try:
        tender_exists = db.get(Tender, tender_uuid) is not None
    finally:
        db.close()
    if not tender_exists:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Tender not found")
        return

    await websocket.accept()

    settings = get_settings()
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    try:
        # TRK-04: send current state immediately, before subscribing to new
        # events, so a client that reconnects mid-run sees where things
        # actually stand right now instead of a blank screen until the
        # next update happens to fire.
        latest = get_latest_progress(tender_id)
        if latest:
            await websocket.send_json(latest)
            if latest.get("status") in _TERMINAL_STATUSES:
                return  # already finished before this client even connected

        await pubsub.subscribe(f"tender:{tender_id}:progress")

        while True:
            # Poll with a short timeout instead of blocking forever, so a
            # client disconnect (caught via receive below) is noticed
            # promptly rather than after the next progress event.
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is not None:
                payload = json.loads(message["data"])
                await websocket.send_json(payload)
                if payload.get("status") in _TERMINAL_STATUSES:
                    break

            # Non-blocking check for the client closing the connection.
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()
        await redis_client.close()
