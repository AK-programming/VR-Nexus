"""
Task 1.2.4 - Role-based access control middleware
Linked requirement: AUTH-04

FastAPI doesn't have "middleware" in the Express/Django sense for
per-route auth - the idiomatic equivalent is a *dependency* that every
protected route declares. That's what get_current_user and require_role
are: attach them to a route and FastAPI runs them before your route body,
rejecting the request with 401/403 if they fail. This is how AUTH-04 gets
enforced "across all API endpoints" - every future router (tenders,
documents, users) imports require_role from here rather than re-implementing
auth checks per route.

This file replaces the DEV_PRINCIPAL stub that the standalone Section 6
backend shipped: that copy had no users table to authenticate against, so
it faked a principal. Here the real one is available, and the library routes
depend on get_current_user like every other route.
"""
import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TokenType, decode_token
from app.models.enums import FeatureKey, UserRole
from app.models.user import User

# HTTPBearer just extracts the "Authorization: Bearer <token>" header for
# us and returns 403 automatically if it's missing entirely.
bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != TokenType.ACCESS.value:
        # Either the signature/expiry check failed, or someone tried to
        # authenticate with a refresh token instead of an access token.
        raise credentials_error

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise credentials_error

    try:
        user_id = uuid.UUID(user_id_raw)
    except ValueError:
        raise credentials_error

    user: Optional[User] = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error

    return user


def require_role(*allowed_roles: UserRole):
    """Dependency factory - use as Depends(require_role(UserRole.ADMIN)).

    Deliberately built as a factory (not a single fixed dependency) so a
    route can require exactly the roles it needs, e.g.
    Depends(require_role(UserRole.ADMIN)) for admin-only routes, while
    Depends(get_current_user) alone is enough for "any logged-in user."
    """

    def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user

    return _check_role


def require_feature(feature: FeatureKey):
    """Dependency factory for the per-user feature grants added alongside
    require_role - use as Depends(require_feature(FeatureKey.DOCUMENTS)).

    An ADMIN always passes, full stop: admins have complete access by
    definition and were never meant to need a grant checked off for them.
    A USER passes only when `feature.value` is in their feature_access
    list, which starts empty on every new account (see the User model) and
    is edited exclusively through the admin-only routes in
    app/api/routes/admin.py.

    This is the enforcement half. The React sidebar and route guards hide
    what a user cannot reach so the app does not dangle links that 403, but
    hiding a link is not access control - this dependency is what actually
    stops the request if someone calls the API directly without the grant.
    """

    def _check_feature(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.ADMIN:
            return current_user

        if feature.value not in (current_user.feature_access or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You do not have access to this section ({feature.value}). "
                    "Ask an administrator to grant it from the Users page."
                ),
            )
        return current_user

    return _check_feature


def require_any_feature(*features: FeatureKey):
    """Like require_feature, but passes when the user holds ANY one of
    several grants — use as
    Depends(require_any_feature(FeatureKey.DOCUMENTS, FeatureKey.DOCUMENTS_UPLOAD)).

    Exists for the handful of routes that sit on the boundary between two
    checkboxes: uploading a document (and completing that one upload's own
    indexing run) only needs DOCUMENTS_UPLOAD, but an account with the
    broader DOCUMENTS grant should not lose the ability to upload just
    because it predates the split. Everywhere else, prefer require_feature
    with a single key — this is for genuine either/or cases, not a way to
    avoid deciding which single feature a route belongs to.
    """

    def _check_any_feature(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.ADMIN:
            return current_user

        granted = set(current_user.feature_access or [])
        if not any(f.value in granted for f in features):
            names = ", ".join(f.value for f in features)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You do not have access to this section ({names}). "
                    "Ask an administrator to grant it from the Users page."
                ),
            )
        return current_user

    return _check_any_feature
