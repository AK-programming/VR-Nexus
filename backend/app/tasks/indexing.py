"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.tasks.library_indexing

READ THIS BEFORE ASSUMING THE TASK NAMES ARE DEAD TOO. They are not. The tasks
in `library_indexing` are deliberately still registered under their original
`app.tasks.indexing.*` names, because a Celery task's registered name is the
routing key carried inside every queued message. Renaming the tasks would
orphan any message already sitting in Redis when the merged backend is
deployed: the worker would receive it, fail to find a task by that name and
reject it. So the module moved and the names stayed. `app/tasks/__init__.py`
records the same point.

That is exactly why this file must raise rather than sit here importable. A
stray `import app.tasks.indexing` would register a *second* set of tasks under
those same names, and the last registration to run wins — meaning which
implementation actually processes a job would depend on import order.

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. Celery does
not reach it either: `app/celery_app.py` lists its task modules explicitly
rather than walking the package.

Left in place rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it is safe and encouraged.
"""

raise ImportError(
    "app.tasks.indexing is a tombstone from the pre-merge flat backend. The "
    "tasks still carry the app.tasks.indexing.* names, but they are defined in "
    "app.tasks.library_indexing — import that instead."
)
