"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.search

Same responsibility (pgvector similarity search over library chunks, plus the
duplicate-detection query behind DUPLICATE_SIMILARITY_THRESHOLD). The live
module queries the `Chunk` model from the `app.models` package and therefore
sees the columns revision 0b55a5033c01 added — `category`, `phase`,
`image_paths` — which this copy's model definition did not have.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.search is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.search instead."
)
