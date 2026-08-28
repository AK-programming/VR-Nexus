"""TOMBSTONE — do not import, do not revive.

This was the WebSocket endpoint in the earlier flat-layout backend. The merged
backend has two WebSocket routers, deliberately separate, and neither is this
one:

    app.api.routes.library_ws   /ws/library/{job_id}    library index progress
    app.api.routes.ws           /ws/tenders/{id}/progress  tender pipeline

They are separate because the two progress systems are separate: the library
publishes on `library:progress:{job_id}` and replays its snapshot from the
persisted `index_jobs` row, while the tender side publishes on
`tender:{id}:progress` and keeps a 24h-TTL `tender:{id}:progress:latest` key.
Different channels, different payload shapes, different replay semantics.

This module also accepted connections without authenticating them, because the
flat backend had no auth. Both live routers read a JWT from the `token` query
parameter — a query parameter rather than a header because the browser
WebSocket constructor cannot set request headers.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.api.ws is a tombstone from the pre-merge flat backend and was "
    "unauthenticated. Use app.api.routes.library_ws or app.api.routes.ws."
)
