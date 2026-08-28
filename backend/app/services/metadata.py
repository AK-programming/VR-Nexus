"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.metadata

Same responsibility (auto-tagging a library document's category, phase and
keywords). The live module writes into the columns the migration chain actually
created — `documents.doc_type`, `documents.auto_tagged_fields`, and
`chunks.category` / `chunks.phase` from revision 0b55a5033c01 — against the
`app.models` package. This copy targeted the flat `app/models.py`, which is
itself a tombstone shadowed by that package.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.metadata is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.metadata instead."
)
