"""Business-logic services, kept separate from route handlers so the same
logic (extraction, chunking, progress broadcasting) can be reused by a
future Celery worker without importing FastAPI request/response code.

Two families live here and they are deliberately not merged:

  * The tender pipeline — chunking, pdf_extraction, extraction,
    pipeline_stages, progress, tender_storage. Page-oriented, ~2000-token
    chunks, progress keyed by tender_id.
  * The Evidence Library — the `library/` subpackage. Section-oriented,
    ~800-token chunks, progress keyed by index job id, its own storage root
    and its own parsers.

`chunking` and `progress` exist in both with the same names and different
behaviour, which is why the library's are namespaced under `library/` rather
than being flattened into this package.
"""
