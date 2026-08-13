"""Progress publishing over Redis pub/sub (LIB-UI-05).

The worker publishes; the API's WebSocket endpoint subscribes and forwards.
Job state is also persisted to index_jobs so a client that connects late — or
reloads mid-run — can be shown current state rather than nothing.
"""
import json
import logging
import uuid

import redis

from app.config import settings
from app.models import STAGE_LABELS, JobStage

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def channel_for(job_id: uuid.UUID | str) -> str:
    return f"library:progress:{job_id}"


def publish(
    job_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    stage: JobStage,
    progress: int,
    message: str = "",
) -> None:
    """Push a progress event. Never raises — a dropped progress frame must not
    fail the indexing job that emitted it."""
    event = {
        "job_id": str(job_id),
        "document_id": str(document_id),
        "stage": stage.value,
        "label": STAGE_LABELS[stage],
        "progress": max(0, min(100, progress)),
        "message": message,
    }
    try:
        get_redis().publish(channel_for(job_id), json.dumps(event))
    except Exception as exc:
        logger.warning("Progress publish failed for job %s: %s", job_id, exc)
