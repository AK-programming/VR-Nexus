"""
Request/response shapes for the admin-only Settings screen: an API key per
LLM provider (Anthropic, OpenAI, Gemini), which provider+model each task
calls, and the per-model pricing table — all editable at runtime (see
app/services/app_settings.py and app/api/routes/admin.py's settings
routes). Kept separate from schemas/admin.py the same way that file is kept
separate from schemas/auth.py - a different admin sub-screen, imported only
by the settings routes.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ModelPricing(BaseModel):
    """USD per MILLION tokens for one model id."""

    input: float = Field(ge=0)
    output: float = Field(ge=0)


class ProviderKeyStatus(BaseModel):
    """One provider's API key state — never the real key, only whether one
    is configured (and where it came from) and a masked preview an admin
    can use to recognise it. One of these per app_settings.PROVIDERS."""

    configured: bool
    source: str  # "settings" | "env" | "none"
    masked: str = ""


class TaskModelSelection(BaseModel):
    """Which provider+model one task (app_settings.MODEL_TASKS) calls."""

    provider: str
    model: str


class AppSettingsOut(BaseModel):
    """GET /api/admin/settings."""

    #: One entry per app_settings.PROVIDERS ("anthropic", "openai", "gemini").
    provider_keys: dict[str, ProviderKeyStatus]
    pricing: dict[str, ModelPricing]
    #: Which model ids in `pricing` are admin-set overrides rather than the
    #: static config.py default — drives an "edited" badge in the UI.
    overridden_models: list[str] = []
    last_pricing_refresh_at: Optional[datetime] = None
    last_pricing_refresh_result: Optional[str] = None
    #: Effective provider+model per task ("extraction", "reasoning") —
    #: override if one is set, otherwise the config.py default (always
    #: provider "anthropic"). See app_settings.MODEL_TASKS /
    #: get_effective_model_overrides.
    model_overrides: dict[str, TaskModelSelection] = {}
    #: Which entries in `model_overrides` are admin-set rather than the
    #: config.py default — same "edited" badge idea as `overridden_models`.
    overridden_model_tasks: list[str] = []
    #: Model ids in `pricing`, grouped by which provider they belong to —
    #: lets the Settings screen filter a task's model dropdown to the
    #: provider currently selected for it, without hand-maintaining a
    #: second list of "which models does each provider have" on the
    #: frontend. Computed from `pricing`'s keys by id prefix (see
    #: app/api/routes/admin.py's _group_models_by_provider) — a model id
    #: this app has never priced can't be selected, same as today.
    models_by_provider: dict[str, list[str]] = {}


class SetApiKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)


class SetPricingRequest(BaseModel):
    """PUT body: the complete pricing table as the admin wants it saved
    (defaults the screen showed, plus whatever they edited) - see
    app_settings.set_pricing_overrides' docstring for why this is a full
    replacement rather than a patch."""

    pricing: dict[str, ModelPricing]


class SetModelOverridesRequest(BaseModel):
    """PUT body: the complete per-task provider+model selection as the
    admin wants it saved - one entry per app_settings.MODEL_TASKS, same
    full-replacement shape as SetPricingRequest. A task left on its default
    provider+model is dropped back to "no override" by
    app_settings.set_model_overrides, so leaving a task's dropdowns on the
    default option is indistinguishable from never having touched it."""

    model_overrides: dict[str, TaskModelSelection]


class PricingRefreshResponse(BaseModel):
    success: bool
    message: str
    updated_models: list[str] = []
