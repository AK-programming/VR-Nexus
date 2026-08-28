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
from app.models.enums import UserRole
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
