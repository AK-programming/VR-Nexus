"""
The Users admin page's backend - client-requested feature from a review
meeting: an admin role with complete access, and a Users tab (admin-only)
that lists every account and lets the admin tick which optional sections
(Documents, AI Assistant, Tender Analysis, Tender Tools) each one can reach.

Every route here is behind require_role(UserRole.ADMIN) - see app/api/deps.py
- so a non-admin gets a plain 403 before either handler body runs. This was
originally a small, two-route surface: list users, and replace one user's
feature_access list. Deletion was added afterward - stray accounts (a
dev-testing signup, a mistaken invite) had no way to leave the table once
they were in it - so it follows the same guard and the same "not for an
ADMIN row" carve-out as the access-grant route above it.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.config import get_settings
from app.core.database import get_db
from app.models.document import Document
from app.models.enums import UserRole
from app.models.tender import Tender
from app.models.user import User
from app.schemas.admin import AdminUserOut, UpdateUserAccessRequest
from app.schemas.admin_settings import (
    AppSettingsOut,
    ModelPricing,
    PricingRefreshResponse,
    ProviderKeyStatus,
    SetApiKeyRequest,
    SetModelOverridesRequest,
    SetPricingRequest,
    TaskModelSelection,
)
from app.services import app_settings as app_settings_service

router = APIRouter(prefix="/api/admin", tags=["admin"])
_settings = get_settings()


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    _admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> list[User]:
    """Every account, newest first - the Users table's only data source."""
    return db.query(User).order_by(User.created_at.desc()).all()


@router.patch("/users/{user_id}/access", response_model=AdminUserOut)
def update_user_access(
    user_id: uuid.UUID,
    data: UpdateUserAccessRequest,
    _admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    """Replaces one user's feature_access list wholesale.

    Rejects editing an ADMIN row here on purpose - an admin's access is
    "everything", unconditionally, by require_feature's own admin bypass,
    so a checkbox panel that appeared to control it would be lying to
    whoever is looking at it.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts already have full access and are not edited here.",
        )

    user.feature_access = [feature.value for feature in data.feature_access]
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    """Removes one account.

    Blocked in three cases rather than left to the database to reject:
    deleting the signed-in admin's own row would strand the request that
    is doing the deleting; an ADMIN row is excluded for the same reason
    `update_user_access` excludes it - there is no action here that means
    anything for an admin's access; and an account that has actually
    uploaded a document or a tender is left alone, because `uploaded_by`
    is a nullable foreign key precisely so a deletion elsewhere never
    silently orphans a file - orphaning it here by default would be the
    same mistake. The admin is told to deal with that content first
    rather than have it happen invisibly underneath them.
    """
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account.",
        )

    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts are not deleted here.",
        )

    has_uploads = (
        db.query(Document.id).filter(Document.uploaded_by == user.id).first() is not None
        or db.query(Tender.id).filter(Tender.uploaded_by == user.id).first() is not None
    )
    if has_uploads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This account has uploaded documents or tenders, so it can't be "
                "deleted. Reassign or remove that content first."
            ),
        )

    db.delete(user)
    db.commit()


# --- Settings: per-provider API keys + per-task model selection + pricing -
#
# Client-requested follow-up: an expired or compromised API key was "a big
# issue" with no way to fix it short of editing .env and restarting the
# backend, and pricing could drift from Anthropic's real rates with no way
# to notice or correct it short of the same manual edit. Extended by a later
# follow-up: the admin wanted to point a task at OpenAI or Gemini instead of
# Anthropic, entering that provider's own key and picking its model. These
# routes let an admin rotate any provider's key and adjust model selection
# and pricing at runtime - see app/services/app_settings.py's module
# docstring for how a saved key takes effect without a restart, and
# refresh_pricing_from_anthropic's docstring for exactly how (and how
# reliably) the "Refresh" button works.


def _group_models_by_provider(model_ids: list[str]) -> dict[str, list[str]]:
    """Buckets pricing-table model ids by provider, purely by id prefix -
    "claude-" -> anthropic, "gpt-"/"o1-"/"o3-"/"o4-"/"chatgpt-" -> openai,
    "gemini-" -> gemini. Good enough because the three providers this app
    supports never overlap in how they name models; a model id that matches
    none of these prefixes is left out of every provider's list rather than
    guessed at, so it simply can't be selected from a task's dropdown until
    its id is recognised (or the prefix list below is extended).
    """
    buckets: dict[str, list[str]] = {p: [] for p in app_settings_service.PROVIDERS}
    openai_prefixes = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")
    for model_id in sorted(model_ids):
        if model_id.startswith("claude-"):
            buckets["anthropic"].append(model_id)
        elif model_id.startswith(openai_prefixes):
            buckets["openai"].append(model_id)
        elif model_id.startswith("gemini-"):
            buckets["gemini"].append(model_id)
    return buckets


@router.get("/settings", response_model=AppSettingsOut)
def get_app_settings(
    _admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    row = app_settings_service.get_row(db)

    pricing = app_settings_service.get_effective_pricing_table(db)
    overridden = sorted((row.pricing_overrides or {}).keys())
    overridden_tasks = sorted((row.model_overrides or {}).keys())
    model_overrides = {
        task: TaskModelSelection(**selection)
        for task, selection in app_settings_service.get_effective_model_overrides(db).items()
    }

    return AppSettingsOut(
        provider_keys={
            provider: ProviderKeyStatus(**app_settings_service.provider_key_status(provider, db))
            for provider in app_settings_service.PROVIDERS
        },
        pricing={model_id: ModelPricing(**rates) for model_id, rates in pricing.items()},
        overridden_models=overridden,
        last_pricing_refresh_at=row.last_pricing_refresh_at,
        last_pricing_refresh_result=row.last_pricing_refresh_result,
        model_overrides=model_overrides,
        overridden_model_tasks=overridden_tasks,
        models_by_provider=_group_models_by_provider(list(pricing.keys())),
    )


@router.put("/settings/api-key/{provider}", response_model=AppSettingsOut)
def update_api_key(
    provider: str,
    data: SetApiKeyRequest,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    """Rotates one provider's shared API key. Takes effect for the very next
    LLM call routed to that provider, on every worker - see
    app/services/app_settings.py's key_generation() for how the cached
    client invalidates without a restart. Not verified against the provider
    before saving (see set_api_key's docstring)."""
    try:
        app_settings_service.set_api_key(db, provider, data.api_key, admin_user_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return get_app_settings(_admin=admin, db=db)


@router.delete("/settings/api-key/{provider}", response_model=AppSettingsOut)
def revert_api_key(
    provider: str,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    """Clears the Settings-stored key for one provider, reverting to
    whatever that provider's .env key is set to (or "none" if that's blank
    too)."""
    try:
        app_settings_service.clear_api_key(db, provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return get_app_settings(_admin=admin, db=db)


@router.put("/settings/pricing", response_model=AppSettingsOut)
def update_pricing(
    data: SetPricingRequest,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    """Saves the complete pricing table shown on the settings screen -
    whatever the admin edited by hand, or the result of a prior Refresh
    click they are now confirming/adjusting."""
    overrides = {model_id: rates.model_dump() for model_id, rates in data.pricing.items()}
    try:
        app_settings_service.set_pricing_overrides(db, overrides)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return get_app_settings(_admin=admin, db=db)


@router.put("/settings/models", response_model=AppSettingsOut)
def update_model_overrides(
    data: SetModelOverridesRequest,
    admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> AppSettingsOut:
    """Saves which provider+model each task (extraction, reasoning - see
    app/services/app_settings.py's MODEL_TASKS) actually calls. Needs no
    client rebuild and no restart: provider+model are just read fresh on
    extraction.py's / library/llm.py's very next call, unlike an API key
    change which requires the generation-counter dance in app_settings.py
    (a task moved onto a provider with no client built yet still gets one
    built on that next call, same as any cache miss). Not verified against
    the provider before saving - the same posture as the API key and
    pricing routes above; an unknown model id will surface as a normal API
    error on the next extraction or Ask call rather than being caught here.
    """
    overrides = {task: selection.model_dump() for task, selection in data.model_overrides.items()}
    try:
        app_settings_service.set_model_overrides(db, overrides)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return get_app_settings(_admin=admin, db=db)


@router.post("/settings/pricing/refresh", response_model=PricingRefreshResponse)
def refresh_pricing(
    _admin: User = Depends(require_role(UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> PricingRefreshResponse:
    """Best-effort: tries to read current per-token prices off Anthropic's
    own public pricing page and update any model this app knows about.
    Anthropic has no pricing API, so this is a page scrape - it can, and
    periodically will, find nothing to update if the page's layout doesn't
    match what this looks for. `success=False` with a message is the normal
    outcome of that, not a bug; editing the table by hand right below this
    button always works regardless of what Refresh finds.
    """
    result = app_settings_service.refresh_pricing_from_anthropic(db)
    return PricingRefreshResponse(
        success=result.success, message=result.message, updated_models=result.updated_models
    )
