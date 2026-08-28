"""TOMBSTONE — do not import, do not revive.

Superseded by:

    app.services.library.llm

The live module is the one to read if you are looking at LLM configuration. It
uses the `openai` client with a configurable `base_url` and `model`, exactly as
this one did, with one deliberate difference recorded in its own docstring: it
does not send a `User-Agent` override. This copy set
`default_headers={"User-Agent": _settings.OPENAI_USER_AGENT}` in order to
present itself as a different client to a third-party router that allowlists
User-Agents. The merged Settings has no OPENAI_USER_AGENT field at all, so
reviving this module would raise AttributeError immediately.

The project's own stated rule, from the prototype's .env.example: "Sent as the
User-Agent on every chat call. Identify this application; do not impersonate
another client."

Nothing in the running tree imports this module — verified by grep across
app/api, app/services and app/tasks before this file was emptied. It is left as
a tombstone rather than deleted because the merge was performed with tooling
that cannot delete files. Deleting it outright is safe and encouraged.
"""

raise ImportError(
    "app.services.llm is a tombstone from the pre-merge flat backend. "
    "Use app.services.library.llm instead."
)
