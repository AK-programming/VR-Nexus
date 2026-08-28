"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.parsers.base

Defines the parser base class and the shared file-resolution helper. The live
copy resolves paths against `LIBRARY_STORAGE_DIR`; this one used the flat
backend's single `STORAGE_DIR`, a setting that no longer exists on the merged
Settings and would be silently ignored (`extra="ignore"`) rather than raising.

Unreachable in practice — `app/services/parsers/__init__.py` raises first, so
this module is never executed. The raise below is a second line of defence for
anyone who copies the file elsewhere.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged.
"""

raise ImportError(
    "app.services.parsers.base is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.parsers.base instead."
)
