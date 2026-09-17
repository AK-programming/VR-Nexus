/**
 * The API Usage feature's wire contract, mirrored from
 * backend/app/schemas/usage.py.
 *
 * Kept separate from models/admin.ts for the same reason admin.ts is kept
 * separate from auth.ts: a distinct backend module (schemas/usage.py) and a
 * distinct pair of consumers (usageService.ts, ApiUsagePage.tsx, and the
 * per-tender usage badge on TenderReviewPage.tsx).
 *
 * `purpose` is a plain string union rather than reusing `isFeatureKey`'s
 * pattern (no normalize function here): unlike an admin-listed user's
 * `feature_access`, a usage row's `purpose` is never rendered as a checkbox
 * a person can toggle, so there is nothing for an unrecognised value to
 * silently break - `PURPOSE_LABELS` below falls back to the raw string for
 * any purpose this build does not have a label for, and every list still
 * renders.
 */

/** Backend `UsagePurpose` (app/models/enums.py). */
export type UsagePurpose =
  | 'tender_extraction'
  | 'tender_metadata'
  | 'library_tagging'
  | 'library_ask'

export const PURPOSE_LABELS: Record<UsagePurpose, string> = {
  tender_extraction: 'Tender extraction',
  tender_metadata: 'Tender metadata',
  library_tagging: 'Library auto-tagging',
  library_ask: 'Library Ask',
}

export function formatPurpose(purpose: string): string {
  return PURPOSE_LABELS[purpose as UsagePurpose] ?? purpose
}

/**
 * Backend `UsageScope`. "all" for an admin (every user's calls), "own"
 * for everyone else (the signed-in caller's calls only) — enforced
 * server-side in api/routes/usage.py, not just a client-side label.
 * `by_user` on `UsageSummary` is always `[]` when scope is "own", since a
 * breakdown by user is meaningless once the data is already one person's.
 */
export type UsageScope = 'all' | 'own'

/** Backend `UsageTotals`. */
export interface UsageTotals {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  total_cost_usd: number
  total_latency_ms: number
  avg_latency_ms: number
}

/** Backend `UsageByModel`. */
export interface UsageByModel {
  model: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  avg_latency_ms: number
}

/** Backend `UsageByPurpose`. */
export interface UsageByPurpose {
  purpose: UsagePurpose
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  avg_latency_ms: number
}

/** Backend `UsageByUser`. */
export interface UsageByUser {
  user_id: string | null
  user_name: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
  avg_latency_ms: number
}

/** GET /api/usage/summary — backend `UsageSummaryOut`. */
export interface UsageSummary {
  scope: UsageScope
  totals: UsageTotals
  by_model: UsageByModel[]
  by_purpose: UsageByPurpose[]
  by_user: UsageByUser[]
}

/**
 * Backend `UsageDailyPoint`. Two granularities share this shape — see the
 * backend schema's own docstring:
 *
 *   - Daily-aggregate (`time` absent): one point per calendar day, figures
 *     are that whole day's totals.
 *   - Per-call (`time` set, an ISO timestamp): one point per individual
 *     API call — `date` is still that call's day, but `time` is what the
 *     chart actually plots against, and the figures are that ONE call's
 *     own numbers, not a running total. The backend only returns this
 *     mode when every call in range fell on a single day; ApiUsagePage
 *     checks `time` on the first point to know which mode it got back.
 */
export interface UsageDailyPoint {
  date: string
  time?: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

/** GET /api/usage/timeseries — backend `UsageTimeseriesOut`. */
export interface UsageTimeseries {
  scope: UsageScope
  points: UsageDailyPoint[]
}

/** GET /api/tenders/{id}/usage — backend `TenderUsageOut`. */
export interface TenderUsage {
  tender_id: string
  total_calls: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cost_usd: number
  total_latency_ms: number
  avg_latency_ms: number
  by_purpose: UsageByPurpose[]
}
