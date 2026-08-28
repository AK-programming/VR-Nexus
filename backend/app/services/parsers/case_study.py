"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.parsers.case_study

Unreachable in practice — `app/services/parsers/__init__.py` raises first, so
this module is never executed. The raise below is a second line of defence for
anyone who copies the file elsewhere.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged.
"""

raise ImportError(
    "app.services.parsers.case_study is a tombstone from the pre-merge flat "
    "backend. Use app.services.library.parsers.case_study instead."
)
