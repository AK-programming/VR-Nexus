"""Tasks package — Celery background jobs.

`library_indexing` is the live task module. `indexing.py` in this package is a
tombstone left from the earlier flat layout and raises on import; do not import
it and do not revive it.

Note that the tasks registered in `library_indexing` deliberately keep the
`app.tasks.indexing.*` names they were first registered under, because the
registered name is the routing key a queued message carries. See that module's
docstring for the full reasoning.
"""
