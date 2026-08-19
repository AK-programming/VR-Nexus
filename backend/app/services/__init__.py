"""Business-logic services, kept separate from route handlers so the same
logic (extraction, chunking, progress broadcasting) can be reused by a
future Celery worker without importing FastAPI request/response code."""
