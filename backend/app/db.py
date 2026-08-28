"""TOMBSTONE — do not import, do not revive.

This module belonged to the earlier flat-layout backend (the VR_Project
prototype) and defined its own SQLAlchemy engine, sessionmaker and declarative
`Base`. The merged backend has exactly one of each and they live in:

    app.core.database    (engine, SessionLocal, Base, get_db)

Two declarative bases in one process is the specific failure this tombstone
exists to prevent: models registered against this Base would be invisible to
`Base.metadata` in alembic/env.py, so `alembic revision --autogenerate` would
propose dropping every table it could not see, and `get_db` from here would
hand out sessions bound to a second engine with its own connection pool.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.db is a tombstone from the pre-merge flat backend. "
    "Use `from app.core.database import Base, get_db` instead."
)
