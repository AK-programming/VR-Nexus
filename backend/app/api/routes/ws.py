"""
Task 7.1.1 - WebSocket streaming during tender processing
Task 7.1.4 - Resume/reconnect handling
Linked requirements: TRK-01, TRK-04

WebSockets can't carry the "Authorization: Bearer <token>" header the way
a normal fetch() can (browsers don't expose custom headers on the
WebSocket constructor), so the access token is passed as a query param
instead: /ws/tenders/{id}/progress?token=<access_token>. It's decoded with
the exact same decode_token() Task 1.2 already uses for HTTP routes, so
the same JWT works everywhere - the client doesn't need a second kind of
credential just for this connection.

TRK-04 (resume/reconnect): the moment a client connects - whether this is
the very first connection or a reconnect after the tab was closed for ten
minutes - they're sent the latest known progress immediately, read from
Redis (see app.services.progress.get_latest_progress), before waiting on
any new event. Progress is never lost between the tender's actual work
and a client happening to be listening.
"""
import asyncio
import json
import uuid

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.security import TokenType, decode_token
from app.models.enums import TenderStatus
from app.models.tender import Tender
from app.models.user import User
from app.services.progress import get_latest_progress

router = APIRouter(tags=["progress"])

_TERMINAL_STATUSES = {TenderStatus.FINALIZED.value, TenderStatus.FAILED.value}


async def _authenticate(websocket: WebSocket, token: str | None) -> User | None:
    if not token:
        return None
    payload = decode_token(token)
    if payload is None or payload.get("type") != TokenType.ACCESS.value:
        return None
    db = SessionLocal()
    try:
        try:
            user_id = uuid.UUID(payload.get("sub"))
        except (TypeError, ValueError):
            return None
        user = db.get(User, user_id)
        return user if user and user.is_active else None
    finally:
        db.close()


@router.websocket("/ws/tenders/{tender_id}/progress")
async def tender_progress_ws(websocket: WebSocket, tender_id: str, token: str | None = None):
    user = await _authenticate(websocket, token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing token")
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
