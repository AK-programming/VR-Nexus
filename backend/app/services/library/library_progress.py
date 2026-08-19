"""
Section 6.2 - Library Frontend & Training Interface
Linked requirement: LIB-UI-05

Deliberately a separate module from app/services/progress.py (Task 7's
tender progress tracker), not a shared one - same Redis pub/sub pattern
(state key + pub/sub channel, so reconnect always sees current state),
but a different channel namespace ("library:progress:{job_id}" vs
"tender:{id}:progress") since these track two unrelated pipelines. Kept
apart so a change to one tracker can't accidentally affect the other.
"""
import json
import logging
import uuid
from typing import Optional

import redis

from app.core.config import get_settings
from app.models.enums import JOB_STAGE_LABELS, JobStage

logger = logging.getLogger(__name__)
_settings = get_settings()
_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(_settings.REDIS_URL, decode_responses=True)
    return _client


def channel_for(job_id) -> str:
    return f"library:progress:{job_id}"


def _state_key(job_id) -> str:
    return f"library:progress:{job_id}:latest"


def publish(
    job_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    stage: JobStage,
    progress: int,
    message: str = "",
) -> dict:
    """Push a progress event. Never raises - a dropped progress frame must
    not fail the indexing job that emitted it."""
    event = {
        "job_id": str(job_id),
        "document_id": str(document_id),
        "stage": stage.value,
        "label": JOB_STAGE_LABELS[stage],
        "progress": max(0, min(100, progress)),
        "message": message,
    }
    payload_json = json.dumps(event)
    try:
        r = get_redis()
        r.set(_state_key(job_id), payload_json, ex=60 * 60 * 24)  # 24h TTL
        r.publish(channel_for(job_id), payload_json)
    except Exception as exc:
        logger.warning("Progress publish failed for job %s: %s", job_id, exc)
    return event


def get_latest_progress(job_id: uuid.UUID | str) -> Optional[dict]:
    """LIB-UI-05 reconnect: what a client should see immediately on
    connect, before any new event has happened yet."""
    r = get_redis()
    raw = r.get(_state_key(job_id))
    return json.loads(raw) if raw else None
