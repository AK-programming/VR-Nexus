"""TOMBSTONE — do not import, do not revive.

This was the Evidence Library router in the earlier flat-layout backend. The
live router is:

    app.api.routes.library

and it is the one registered in app/main.py. The two are not interchangeable:
this version took its principal from the flat backend's no-op `DEV_PRINCIPAL`
stub, so every endpoint here was effectively unauthenticated. The live router
declares `Depends(get_current_user)` and resolves a real JWT. Registering this
module on the app — even accidentally, even second — would expose an
unauthenticated copy of every library endpoint on the same paths.

It also depended on the tombstoned `app.config`, `app.db`, `app.models` and
`app.schemas`, so it could not import cleanly even if someone wanted it to.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.api.library is a tombstone from the pre-merge flat backend and was "
    "unauthenticated. Use app.api.routes.library instead."
)
