"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.embeddings

Same responsibility (turning chunk text into vectors), but the live module is
the one wired to the merged `app.core.config` Settings, which fixes the
provider and dimension as a matched set: EMBEDDING_PROVIDER="fastembed",
EMBEDDING_MODEL="BAAI/bge-base-en-v1.5", EMBEDDING_DIM=768. That 768 is not a
free parameter — `chunks.embedding` and `tender_chunks.embedding` are both
declared `vector(768)` in the migration chain, so a module that produced a
different width would fail on insert rather than at configuration time.

This copy read its settings from the tombstoned `app.config`, so it cannot
import cleanly in any case.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.embeddings is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.embeddings instead."
)
