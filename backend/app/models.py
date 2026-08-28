"""TOMBSTONE — unreachable by construction. Do not revive.

This file is shadowed and can never be imported. `app/models/` exists as a
package, and Python's path finder always prefers a package over a same-named
module in the same directory, so `import app.models` resolves to
`app/models/__init__.py` and this file is never read. The raise below is
therefore documentation, not a guard — it cannot fire.

The live ORM models are the `app.models` package:

    app.models.user, app.models.document, app.models.chunk,
    app.models.tender, app.models.requirement, app.models.index_job, ...

all registered against the single `Base` in `app.core.database`. The flat
prototype declared its models in this one file against its own Base in
`app/db.py`, which is also tombstoned.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged — it removes a
genuinely confusing artifact, since a reader who opens this file has no way to
tell from the filename alone that nothing here runs.
"""

raise ImportError(
    "app/models.py is a tombstone shadowed by the app/models/ package and "
    "cannot be imported. Import from app.models (the package) instead."
)
