/**
 * The admin-only Users page's wire contract, mirrored from
 * backend/app/schemas/admin.py.
 *
 * Kept separate from models/auth.ts for the same reason the backend keeps
 * schemas/admin.py separate from schemas/auth.py: this is a different
 * audience — admin tooling, not the account holder's own session — and only
 * adminService.ts and AdminUsersPage.tsx need it.
 */

import { isFeatureKey } from './auth'
import type { FeatureKey, UserRole } from './auth'

/**
 * Backend `AdminUserOut`. Deliberately not the same shape as `User`
 * (models/auth.ts): this is one row of the Users table as an administrator
 * sees every account, not the signed-in caller's own profile, so it carries
 * `created_at` and drops the fields (`phone_number`, `company`) the table has
 * no column for.
 */
export interface AdminUser {
  id: string
  name: string
  email: string
  role: UserRole
  is_active: boolean
  feature_access: FeatureKey[]
  created_at: string
  last_login_at: string | null
}

/** PATCH /api/admin/users/{id}/access body — backend `UpdateUserAccessRequest`. */
export interface UpdateUserAccessRequest {
  feature_access: FeatureKey[]
}

/**
 * Repairs one admin-listed user the same way `normalizeUser` repairs the
 * signed-in caller's own — an unrecognised role becomes the least-privileged
 * one, and any feature key this build does not know about is dropped rather
 * than rendered as a checkbox nobody can uncheck.
 *
 * Filters through `isFeatureKey` (checked against `FEATURE_KEYS`) rather
 * than a hand-written list of keys here. A hand-written list has already
 * caused one real bug: it was written before `documents_upload` existed, so
 * every admin-listed user silently had that grant stripped back out on
 * every load and after every save, which is why the checkbox looked like it
 * did nothing when clicked - the PATCH succeeded, but the very next
 * normalize pass threw the new grant away again. `isFeatureKey` reads the
 * same `FEATURE_KEYS` array `AdminUsersPage` renders checkboxes from, so a
 * key this list omits and that list includes can no longer happen.
 */
export function normalizeAdminUser(user: AdminUser): AdminUser {
  const role: UserRole = user.role === 'admin' ? 'admin' : 'user'
  const featureAccess = Array.isArray(user.feature_access)
    ? user.feature_access.filter((key): key is FeatureKey => isFeatureKey(key))
    : []

  if (role === user.role && featureAccess.length === user.feature_access.length) {
    return user
  }

  return { ...user, role, feature_access: featureAccess }
}

/**
 * The admin-only Settings screen's wire contract, mirrored from
 * backend/app/schemas/admin_settings.py. See adminService.ts and
 * AdminSettingsPage.tsx — an API key per LLM provider, which provider+model
 * each task calls, and the per-model pricing table, all editable at
 * runtime instead of only via .env.
 */
export interface ModelPricing {
  input: number
  output: number
}

/**
 * Every LLM provider this app can call, mirrored from backend
 * `app/services/app_settings.py`'s `PROVIDERS`. Fixed at three rather than
 * a free-form value — a fourth provider needs real backend client code
 * before it could do anything, so the set stays in sync with the code by
 * construction.
 */
export const PROVIDERS = ['anthropic', 'openai', 'gemini'] as const

export type Provider = (typeof PROVIDERS)[number]

export const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: 'Anthropic',
  openai: 'OpenAI',
  gemini: 'Google Gemini',
}

/** Where a provider's key currently in effect actually came from — drives
 * the "Set in .env" / "Set in Settings" / "Not configured" copy. */
export type ApiKeySource = 'settings' | 'env' | 'none'

export interface ProviderKeyStatus {
  configured: boolean
  source: ApiKeySource
  masked: string
}

/**
 * The two model "slots" the app actually calls, mirrored from backend
 * `app/services/app_settings.py`'s `MODEL_TASKS`:
 *   - "extraction": tender requirement extraction, tender metadata, and
 *     Evidence Library auto-tagging — mechanical, high-volume, cheap-model
 *     work.
 *   - "reasoning": the Evidence Library's grounded Ask — the one call that
 *     weighs evidence and writes prose.
 * Fixed at two entries rather than a free-form list because a third slot
 * would need a new backend call site to actually read it — see that
 * module's own comment on why this isn't just a dict.
 */
export const MODEL_TASKS = ['extraction', 'reasoning'] as const

export type ModelTask = (typeof MODEL_TASKS)[number]

/** What the Settings screen shows next to each task's dropdowns. */
export const MODEL_TASK_LABELS: Record<ModelTask, string> = {
  extraction: 'Tender & library extraction',
  reasoning: 'Evidence Library Ask',
}

export const MODEL_TASK_DESCRIPTIONS: Record<ModelTask, string> = {
  extraction:
    'Tender requirement extraction, tender metadata, and Evidence Library auto-tagging — mechanical, high-volume work, run on a cheaper model.',
  reasoning:
    "The Evidence Library's grounded Ask — the one call that weighs evidence and writes prose.",
}

/** Which provider + model one task calls — backend `TaskModelSelection`. */
export interface TaskModelSelection {
  provider: Provider
  model: string
}

export interface AppSettings {
  /** One entry per `PROVIDERS`. */
  provider_keys: Record<Provider, ProviderKeyStatus>
  pricing: Record<string, ModelPricing>
  /** Model ids in `pricing` that are admin-set overrides rather than the
   * static config.py default. */
  overridden_models: string[]
  last_pricing_refresh_at: string | null
  last_pricing_refresh_result: string | null
  /** Effective provider+model per task ("extraction", "reasoning") — an
   * override if one is set, otherwise the config.py default (always
   * provider "anthropic"). Always has an entry for every `MODEL_TASKS` key. */
  model_overrides: Partial<Record<ModelTask, TaskModelSelection>>
  /** Which entries in `model_overrides` are admin-set rather than the
   * config.py default — same "edited" badge idea as `overridden_models`. */
  overridden_model_tasks: ModelTask[]
  /** Model ids in `pricing`, grouped by provider — what populates a task's
   * model dropdown once a provider is chosen for it. */
  models_by_provider: Partial<Record<Provider, string[]>>
}

export interface SetApiKeyRequest {
  api_key: string
}

export interface SetPricingRequest {
  pricing: Record<string, ModelPricing>
}

export interface SetModelOverridesRequest {
  model_overrides: Partial<Record<ModelTask, TaskModelSelection>>
}

export interface PricingRefreshResponse {
  success: boolean
  message: string
  updated_models: string[]
}
