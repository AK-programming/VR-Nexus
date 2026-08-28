"""TOMBSTONE PACKAGE — do not import, do not revive.

The live parsers are:

    app.services.library.parsers

This package is the earlier flat-layout backend's copy. Raising here makes the
whole package unimportable, which also makes its six submodules (base,
case_study, company, methodology, extract, registry) unreachable — each carries
its own tombstone note for anyone who opens the file directly.

Why the live parsers live under `library/` rather than here: parsing is one of
the places the two halves of the merged backend genuinely differ. The library
parsers are section-oriented and produce library `Chunk` rows; the tender side
parses page-oriented documents through `app.services.pdf_extraction` and
`app.services.chunking` into `TenderTextChunk`. Flattening them into one
`app/services/parsers/` package invites exactly the confusion this tombstone
prevents.

Nothing in the running tree imports this package — verified by grep across
app/api, app/services and app/tasks before these files were emptied. Left in
place rather than deleted because the merge was performed with tooling that
cannot delete files. Deleting the whole `app/services/parsers/` directory is
safe and encouraged.
"""

raise ImportError(
    "app.services.parsers is a tombstone package from the pre-merge flat "
    "backend. Use app.services.library.parsers instead."
)
