/**
 * The API Usage feature's three endpoints: the summary and timeseries
 * (open to every signed-in account, scoped by role), and the per-tender
 * usage badge.
 *
 * Mirrors adminService.ts's shape: a paths object, and functions that wrap
 * `api` with nothing fetch-shaped of their own. The summary and timeseries
 * routes only require a valid session on the backend — `get_current_user`,
 * not `require_role(UserRole.ADMIN)` — because what they return is scoped
 * server-side to the caller: an admin gets everyone's usage, anyone else
 * gets only their own (see backend/app/api/routes/usage.py, and
 * `UsageSummary.scope` / `UsageTimeseries.scope` in models/usage.ts, which
 * say which one actually happened). The tender route only needs the same
 * `tender_analysis` feature grant every other tender route requires (see
 * backend/app/api/routes/tenders.py) and is reachable by any tender-analysis
 * user for their own tenders, not just an admin.
 *
 * Backend reference: backend/app/api/routes/usage.py, backend/app/api/routes/tenders.py.
 */

import { api } from '@/lib/apiClient'
import type { TenderUsage, UsageSummary, UsageTimeseries } from '@/models'

export const USAGE_ENDPOINTS = {
  summary: '/api/usage/summary',
  timeseries: '/api/usage/timeseries',
  tenderUsage: (tenderId: string) => `/api/tenders/${tenderId}/usage`,
} as const

/** Optional inclusive UTC date range, `YYYY-MM-DD`. Omitted entirely means
 * "everything ever recorded" for the summary, and the endpoint's own
 * default (last 30 days) for the timeseries — see usage.py's docstrings. */
export type UsageDateRange = {
  start?: string
  end?: string
}

function rangeQuery(range?: UsageDateRange, userId?: string): string {
  const params = new URLSearchParams()
  if (range?.start) params.set('start', range.start)
  if (range?.end) params.set('end', range.end)
  if (userId) params.set('user_id', userId)
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const usageService = {
  /** Totals plus by-model / by-purpose / by-user breakdowns for the Usage
   * page's stat tiles and tables — everyone's usage for an admin, only the
   * caller's own for anyone else (see `UsageSummary.scope`). */
  async getSummary(range?: UsageDateRange, signal?: AbortSignal): Promise<UsageSummary> {
    return api.get<UsageSummary>(`${USAGE_ENDPOINTS.summary}${rangeQuery(range)}`, { signal })
  },

  /** One point per UTC calendar day, for the Usage page's daily chart —
   * same scoping as `getSummary`. `userId` charts one team member's own
   * calls instead of the team total — admin only, silently ignored by the
   * backend for anyone else (see usage.py's `user_id` param doc), so it is
   * always safe to pass through here rather than gating it client-side. */
  async getTimeseries(range?: UsageDateRange, userId?: string, signal?: AbortSignal): Promise<UsageTimeseries> {
    return api.get<UsageTimeseries>(`${USAGE_ENDPOINTS.timeseries}${rangeQuery(range, userId)}`, { signal })
  },

  /** What one tender's own extraction + metadata calls cost, for the
   * per-tender usage badge on Tender Review. */
  async getTenderUsage(tenderId: string, signal?: AbortSignal): Promise<TenderUsage> {
    return api.get<TenderUsage>(USAGE_ENDPOINTS.tenderUsage(tenderId), { signal })
  },
}
