"""Celery application (LIB-UI-04 — background indexing pipeline)."""
from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "evidence_library",
    broker=_settings.REDIS_URL,
    backend=_settings.REDIS_URL,
    include=["app.tasks.library_indexing", "app.tasks.tender_pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Indexing is CPU-bound (parsing, OCR, ONNX inference). Prefetching would
    # let one busy worker sit on queued jobs while another idles.
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
    result_expires=86400,
    # A large scanned PDF with OCR on every page is slow but not broken. The hard
    # limit is above the soft one so the task gets a chance to record its own
    # failure before being killed.
    task_soft_time_limit=1800,
    task_time_limit=2100,
)

# Celery's `current_app` lives in thread-local storage, and it is only populated
# on the thread that imported this module. FastAPI runs sync route handlers in an
# anyio worker thread, so anything there resolving `current_app` would miss and
# get a lazily-created default app whose broker is amqp://localhost:5672 —
# "Connection refused" on enqueue, with a Redis URL configured correctly. Setting
# the default makes this app the fallback for every thread.
celery_app.set_default()
