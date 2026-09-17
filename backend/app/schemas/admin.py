"""
Request/response shapes for the admin-only Users page (client-requested
feature: an admin role with full access, plus a per-user, per-section
access grant a non-admin starts without and an admin switches on).

Kept as its own module rather than folded into schemas/auth.py because
these shapes are for a different audience - admin-only tooling, not the
account holder's own session - and admin.py's routes are the only thing
that imports it.
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.enums import FeatureKey, UserRole


class AdminUserOut(BaseModel):
    """One row of the Users admin table."""

    id: uuid.UUID
    name: str
    email: str
    role: UserRole
    is_active: bool
    feature_access: list[str]
    created_at: datetime
    last_login_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UpdateUserAccessRequest(BaseModel):
    """PATCH /api/admin/users/{user_id}/access body.

    A full replacement list, not a single toggle - the Users page sends the
    complete set of checked boxes on every click, which keeps this endpoint
    idempotent and means the client never has to reconcile an add/remove
    pair with a list it might not have fetched fresh. `list[FeatureKey]`
    means Pydantic rejects an unknown key outright rather than silently
    storing it.
    """

    feature_access: list[FeatureKey]
