"""TOMBSTONE — unreachable by construction. Do not revive.

This file is shadowed and can never be imported. `app/schemas/` exists as a
package, and Python's path finder always prefers a package over a same-named
module in the same directory, so `import app.schemas` resolves to
`app/schemas/__init__.py` and this file is never read. The raise below is
therefore documentation, not a guard — it cannot fire.

The live Pydantic schemas are the `app.schemas` package:

    app.schemas.auth      (UserOut, TokenResponse, LoginRequest, ...)
    app.schemas.library   (DocumentOut, ChunkOut, IndexJobOut, ...)
    app.schemas.tender    (TenderOut, RequirementOut, ...)

The flat prototype declared all of its schemas in this one file, with no auth
schemas at all because it had no real authentication.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged.
"""

raise ImportError(
    "app/schemas.py is a tombstone shadowed by the app/schemas/ package and "
    "cannot be imported. Import from app.schemas (the package) instead."
)
