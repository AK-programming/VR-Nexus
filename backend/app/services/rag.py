"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.rag

Same responsibility (retrieve-then-generate over the Evidence Library). The
live module composes `app.services.library.search` and
`app.services.library.llm`; this copy composed the flat `app/services/search.py`
and `app/services/llm.py`, both tombstoned, and read its settings from the
tombstoned `app.config`.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.rag is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.rag instead."
)
