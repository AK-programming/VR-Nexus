"""
Task 7.1 - Live Progress Streaming
Linked requirements: TRK-01, TRK-02, TRK-03, TRK-04

Redis is used as the transport (not just an in-process dict) because it's
already provisioned for Celery, and it's what actually makes TRK-04
(resume/reconnect) work correctly: progress state has to survive outside
any single FastAPI worker process/request, and a second browser tab or a
reconnect needs to read the *current* state, not just future pushes.

Two Redis structures per tender:
  - a String key holding the latest progress payload as JSON (read on
    connect/reconnect - TRK-04)
  - a Pub/Sub channel of the same name, published to on every update (read
    live while a WebSocket is open - TRK-01)

This module has no FastAPI imports, so the same publish_progress() call
works from a plain HTTP request handler now (Task 2.1's synchronous
upload-and-process endpoint) and from a Celery worker later (Stage 2-4),
without either one needing to know a WebSocket exists.

Deliberately separate from app/services/library/library_progress.py. That one
tracks Evidence Library indexing jobs on channel `library:progress:{job_id}`
and replays its snapshot from the persisted index_jobs row, because its work
runs in a Celery worker and a client can connect long after a stage passed.
This one tracks the tender pipeline on `tender:{tender_id}:progress` and keeps
its snapshot in Redis. Different keys, different payload shapes, different
consumers - keep them apart.
"""
import json
from datetime import datetime, timezone
from typing import Optional

import redis

from app.core.config import get_settings
from app.models.enums import TenderStatus

_settings = get_settings()
_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True)
    return _redis_client


# TRK-03: the 8 pipeline stages, in order. TenderStatus has a couple of
# extra terminal values (FINALIZED, FAILED) that aren't "steps" themselves,
# so they're excluded from the step count but still valid statuses.
PIPELINE_STAGES: list[TenderStatus] = [
    TenderStatus.UPLOADED,
    TenderStatus.PARSING,
    TenderStatus.CHUNKING,
    TenderStatus.EXTRACTING,
    TenderStatus.MERGING,
    TenderStatus.MATCHING,
    TenderStatus.REPORTING,
    TenderStatus.ASSEMBLING_FOLDER,
    TenderStatus.READY_FOR_REVIEW,
]

STAGE_LABELS: dict[TenderStatus, str] = {
    TenderStatus.UPLOADED: "Uploaded",
    TenderStatus.PARSING: "Parsing",
    TenderStatus.CHUNKING: "Chunking",
    TenderStatus.EXTRACTING: "Extracting requirements",
    TenderStatus.MERGING: "Merging & de-duplicating",
    TenderStatus.MATCHING: "Matching evidence",
    TenderStatus.REPORTING: "Generating report",
    TenderStatus.ASSEMBLING_FOLDER: "Assembling output folder",
    TenderStatus.READY_FOR_REVIEW: "Ready for review",
}


def _channel_key(tender_id: str) -> str:
    return f"tender:{tender_id}:progress"


def _state_key(tender_id: str) -> str:
    return f"tender:{tender_id}:progress:latest"


def publish_progress(
    tender_id: str,
    status: TenderStatus,
    *,
    percent: Optional[int] = None,
    message: Optional[str] = None,
    extracted_requirements_count: Optional[int] = None,
) -> dict:
    """Builds the TRK-02 payload, stores it as the latest state (for
    TRK-04 resume), and publishes it to anyone currently listening
    (TRK-01). Returns the payload so the caller (e.g. the upload endpoint)
    can also persist status/progress_percent onto the Tender row itself."""
    r = get_redis()

    if status in PIPELINE_STAGES:
        step_index = PIPELINE_STAGES.index(status) + 1
    else:
        step_index = len(PIPELINE_STAGES)  # FINALIZED/FAILED: treat as "past the last step"

    computed_percent = percent
    if computed_percent is None:
        computed_percent = round((step_index / len(PIPELINE_STAGES)) * 100)

    payload = {
        "tender_id": tender_id,
        "status": status.value,
        "step_label": STAGE_LABELS.get(status, status.value),
        "current_step": step_index,
        "total_steps": len(PIPELINE_STAGES),
        "percent_complete": computed_percent,
        "message": message,
        "extracted_requirements_count": extracted_requirements_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    payload_json = json.dumps(payload)
    r.set(_state_key(tender_id), payload_json, ex=60 * 60 * 24)  # 24h TTL, plenty for a local run
    r.publish(_channel_key(tender_id), payload_json)
    return payload


def get_latest_progress(tender_id: str) -> Optional[dict]:
    """TRK-04: what a client should see immediately on connect/reconnect,
    before any new event has happened yet."""
    r = get_redis()
    raw = r.get(_state_key(tender_id))
    return json.loads(raw) if raw else None


def get_progress_channel(tender_id: str):
    """Returns a Redis pubsub object already subscribed to this tender's
    channel. Caller is responsible for closing it (see the WebSocket route)."""
    r = get_redis()
    pubsub = r.pubsub()
    pubsub.subscribe(_channel_key(tender_id))
    return pubsub
