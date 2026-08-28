"""TOMBSTONE — do not import, do not revive.

This module belonged to the earlier flat-layout backend (the VR_Project
prototype), which carried its own module-level `settings` object built by a
different Settings class. The merged backend has exactly one configuration
module and it is:

    app.core.config    (Settings + @lru_cache get_settings())

The two are not interchangeable. The flat version exposed a single
`STORAGE_DIR`; the live one splits storage four ways (STORAGE_ROOT,
TENDER_STORAGE_DIR, LIBRARY_STORAGE_DIR, OUTPUT_STORAGE_DIR) and adds the JWT,
Celery and CORS settings the flat prototype never had because its auth was a
hardcoded dev stub. Code that read `settings` from here would silently get
defaults for everything the flat class knew about and AttributeError for the
rest.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.

The raise below makes a stray import fail loudly at import time instead of
quietly configuring half the application from the wrong source.
"""

raise ImportError(
    "app.config is a tombstone from the pre-merge flat backend. "
    "Use `from app.core.config import get_settings` instead."
)
