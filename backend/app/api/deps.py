"""Authentication placeholder.

WBS 1.2 (AUTH-01..06) is owned by another engineer and is Not Started, so there
is no token issuer to validate against yet. Every route depends on
`current_user` so that wiring real JWT verification later is a change to this
file alone rather than to every handler signature.

Until then these endpoints are unauthenticated. Compose binds them to 127.0.0.1
only; do not expose the port until 1.2.x lands.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    id: str
    email: str
    is_authenticated: bool


DEV_PRINCIPAL = Principal(
    id="00000000-0000-0000-0000-000000000000",
    email="dev@local",
    is_authenticated=False,
)


def current_user() -> Principal:
    """FastAPI dependency. Returns a fixed development principal.

    Replace the body with token verification when AUTH-02 exists; raise 401 on
    failure. The signature does not need to change.
    """
    return DEV_PRINCIPAL
