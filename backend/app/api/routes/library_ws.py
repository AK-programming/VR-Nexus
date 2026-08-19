"""Real-time training status over WebSocket (LIB-UI-05).

The worker publishes progress to Redis; this endpoint subscribes to one job's
channel and forwards each frame to the browser.

On connect the current `index_jobs` row is replayed first. Without that, a client
that reloads mid-run — or connects a moment after Train — would sit on an empty
progress bar while the job is already at "Generating Embeddings".
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.database import SessionLocal
from app.models import IndexJob
from app.models.enums import JOB_STAGE_LABELS as STAGE_LABELS, JobStage
from app.services.library import library_progress as progress

logger = logging.getLogger(__name__)

router = APIRouter(tags=["progress"])

# How long to wait on Redis before looping. Short enough that a disconnected
# client is noticed promptly, long enough not to spin.
POLL_TIMEOUT = 1.0

TERMINAL_STAGES = {JobStage.COMPLETE, JobStage.FAILED}


def _snapshot(job_id: uuid.UUID) -> dict | None:
    """Read persisted job state so a late client sees where the run got to."""
    db = SessionLocal()
    try:
        job = db.get(IndexJob, job_id)
        if job is None:
            return None
        return {
            "job_id": str(job.id),
            "document_id": str(job.document_id),
            "stage": job.stage.value,
            "label": STAGE_LABELS[job.stage],
            "progress": job.progress,
            "message": job.message,
            "replayed": True,
        }
    finally:
        db.close()


@router.websocket("/ws/library/{job_id}")
async def job_progress(websocket: WebSocket, job_id: uuid.UUID) -> None:
    await websocket.accept()

    snapshot = await asyncio.to_thread(_snapshot, job_id)
    if snapshot is None:
        await websocket.send_json({"error": "Unknown job id", "job_id": str(job_id)})
        await websocket.close()
        return

    await websocket.send_json(snapshot)

    # A job that finished before the client connected has nothing further to
    # stream; the snapshot above already told the whole story.
    if snapshot["stage"] in {s.value for s in TERMINAL_STAGES}:
        await websocket.close()
        return

    pubsub = None
    try:
        client = progress.get_redis()
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        await asyncio.to_thread(pubsub.subscribe, progress.channel_for(job_id))
    except Exception as exc:
        logger.warning("Could not subscribe to progress for job %s: %s", job_id, exc)
        await websocket.send_json(
            {
                "error": "Live progress is unavailable; poll /api/library/jobs/{id} instead.",
                "job_id": str(job_id),
            }
        )
        await websocket.close()
        return

    try:
        while True:
            message = await asyncio.to_thread(
                pubsub.get_message, timeout=POLL_TIMEOUT
            )

            if message is None:
                # Keeps proxies from dropping an idle socket during a long parse,
                # and surfaces a dead client as a WebSocketDisconnect.
                await websocket.send_json({"type": "ping", "job_id": str(job_id)})
                continue

            data = message.get("data")
            if not data:
                continue

            try:
                event = json.loads(data)
            except (TypeError, ValueError):
                logger.warning("Malformed progress frame on job %s", job_id)
                continue

            await websocket.send_json(event)

            if event.get("stage") in {s.value for s in TERMINAL_STAGES}:
                break

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Progress stream error for job %s: %s", job_id, exc)
    finally:
        if pubsub is not None:
            try:
                await asyncio.to_thread(pubsub.close)
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            # Already closed by the client.
            pass
