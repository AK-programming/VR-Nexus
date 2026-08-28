"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.storage      Evidence Library files
    app.services.tender_storage       tender uploads

Splitting this in two is the point. The flat backend had one storage module
resolving everything under a single `STORAGE_DIR` setting. The merged Settings
has four roots — STORAGE_ROOT, TENDER_STORAGE_DIR, LIBRARY_STORAGE_DIR,
OUTPUT_STORAGE_DIR — because library assets, tender uploads and generated
output folders have different lifetimes and different volume mounts in
docker-compose.yml. `STORAGE_DIR` no longer exists as a Settings field, and
because Settings is configured with `extra="ignore"` it would not error if
someone set it in .env — it would simply be swallowed, and paths would fall
back to their defaults. That silent failure is exactly why this module raises
instead of being left importable.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.storage is a tombstone from the pre-merge flat backend. Use "
    "app.services.library.storage or app.services.tender_storage instead."
)
