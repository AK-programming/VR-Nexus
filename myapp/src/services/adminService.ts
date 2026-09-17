/**
 * The admin-only Users page's two endpoints.
 *
 * Mirrors authService.ts's shape: a paths object, and functions that wrap
 * `api` with nothing fetch-shaped of their own. Both routes are guarded on
 * the backend by `require_role(UserRole.ADMIN)` — see
 * backend/app/api/routes/admin.py — so a non-admin caller gets a plain 403
 * rather than a filtered response; this file does not attempt to hide the
 * "Users" screen from anyone, that is `RequireAdmin`'s job
 * (@/app/guards.tsx) and the Sidebar's.
 *
 * Backend reference: backend/app/api/routes/admin.py.
 */

import { api } from '@/lib/apiClient'
import type {
  AdminUser,
  AppSettings,
  PricingRefreshResponse,
  Provider,
  SetApiKeyRequest,
  SetModelOverridesRequest,
  SetPricingRequest,
  UpdateUserAccessRequest,
} from '@/models'
import { normalizeAdminUser } from '@/models'

export const ADMIN_ENDPOINTS = {
  users: '/api/admin/users',
  userAccess: (userId: string) => `/api/admin/users/${userId}/access`,
  user: (userId: string) => `/api/admin/users/${userId}`,
  settings: '/api/admin/settings',
  /** One key per provider now - matches the backend's
   * PUT/DELETE /api/admin/settings/api-key/{provider}. */
  settingsApiKey: (provider: Provider) => `/api/admin/settings/api-key/${provider}`,
  settingsPricing: '/api/admin/settings/pricing',
  settingsPricingRefresh: '/api/admin/settings/pricing/refresh',
  settingsModels: '/api/admin/settings/models',
} as const

export const adminService = {
  /** Every account, newest first — the Users table's only data source. */
  async listUsers(signal?: AbortSignal): Promise<AdminUser[]> {
    const users = await api.get<AdminUser[]>(ADMIN_ENDPOINTS.users, { signal })
    return users.map(normalizeAdminUser)
  },

  /**
   * Replaces one user's feature_access list wholesale — a full replacement,
   * not a single toggle, so the caller always sends the complete set of
   * checked boxes. Rejected by the backend with a 400 if `userId` belongs to
   * an admin account, since an admin's access is unconditional and not
   * edited here.
   */
  async updateUserAccess(
    userId: string,
    payload: UpdateUserAccessRequest,
    signal?: AbortSignal,
  ): Promise<AdminUser> {
    const user = await api.patchJson<AdminUser>(ADMIN_ENDPOINTS.userAccess(userId), payload, {
      signal,
    })
    return normalizeAdminUser(user)
  },

  /**
   * Removes one account outright. Rejected by the backend with a 400 for
   * the admin's own row, for another ADMIN row, or for an account that has
   * uploaded a document or a tender — see delete_user's docstring in
   * backend/app/api/routes/admin.py for why each of those is refused
   * rather than silently orphaning data.
   */
  async deleteUser(userId: string, signal?: AbortSignal): Promise<void> {
    await api.delete(ADMIN_ENDPOINTS.user(userId), { signal })
  },

  /** The current Anthropic API key (masked) and effective pricing table —
   * the admin-only Settings screen's only data source. */
  async getSettings(signal?: AbortSignal): Promise<AppSettings> {
    return api.get<AppSettings>(ADMIN_ENDPOINTS.settings, { signal })
  },

  /** Rotates one provider's shared API key. Takes effect for the very
   * next LLM call routed to that provider, on every worker — see
   * backend/app/services/app_settings.py. */
  async setApiKey(
    provider: Provider,
    payload: SetApiKeyRequest,
    signal?: AbortSignal,
  ): Promise<AppSettings> {
    return api.putJson<AppSettings>(ADMIN_ENDPOINTS.settingsApiKey(provider), payload, { signal })
  },

  /** Reverts one provider's key to whatever that provider's .env variable
   * is set to (or "none" if that's blank too). */
  async clearApiKey(provider: Provider, signal?: AbortSignal): Promise<AppSettings> {
    return api.delete<AppSettings>(ADMIN_ENDPOINTS.settingsApiKey(provider), { signal })
  },

  /** Saves the complete pricing table shown on the screen — a full replace,
   * not a per-row patch (see SetPricingRequest's backend docstring). */
  async setPricing(payload: SetPricingRequest, signal?: AbortSignal): Promise<AppSettings> {
    return api.putJson<AppSettings>(ADMIN_ENDPOINTS.settingsPricing, payload, { signal })
  },

  /** Best-effort attempt to pull current prices off Anthropic's own pricing
   * page — see the backend route's docstring for exactly how (un)reliable
   * this is. Always resolves with a result object, never throws for "found
   * nothing" — only a real network/server failure throws. */
  async refreshPricing(signal?: AbortSignal): Promise<PricingRefreshResponse> {
    return api.postEmpty<PricingRefreshResponse>(ADMIN_ENDPOINTS.settingsPricingRefresh, {
      signal,
    })
  },

  /** Saves which model id each task (extraction, reasoning) calls — a full
   * replacement of the dropdown selections shown, same shape as
   * `setPricing`. Takes effect on the very next call, no restart. */
  async setModelOverrides(
    payload: SetModelOverridesRequest,
    signal?: AbortSignal,
  ): Promise<AppSettings> {
    return api.putJson<AppSettings>(ADMIN_ENDPOINTS.settingsModels, payload, { signal })
  },
}
