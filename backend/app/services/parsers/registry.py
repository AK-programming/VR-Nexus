"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.parsers.registry

Maps a document type to the parser that handles it. This is the module most
likely to be imported by mistake, because the flat path
`app.services.parsers.registry` reads as the obvious place for a registry to
live — hence the explicit raise.

Unreachable in practice — `app/services/parsers/__init__.py` raises first, so
this module is never executed. The raise below is a second line of defence for
anyone who copies the file elsewhere.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged.
"""

raise ImportError(
    "app.services.parsers.registry is a tombstone from the pre-merge flat "
    "backend. Use app.services.library.parsers.registry instead."
)
