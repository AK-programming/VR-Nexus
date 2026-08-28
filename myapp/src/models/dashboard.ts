/**
 * The shapes the dashboard renders.
 *
 * These are UI types, not API types. `src/models/auth.ts` mirrors the backend
 * exactly because those payloads are contracts; nothing here has an endpoint yet,
 * so these describe what the screen needs rather than what a server happens to
 * send. When the API lands, the adapter goes in the service layer and these stay
 * put — which is the point of writing them down now.
 *
 * Every id is a string. Even where the backend ends up using integers, a string
 * key is what React wants and what a URL segment will carry.
 */

/* -------------------------------------------------------------------------- */
/* Summary tiles                                                              */
/* -------------------------------------------------------------------------- */

/** Which glyph a tile draws. The tile maps the name to a component so the data
 *  module never imports React. */
export type StatIconName = 'projects' | 'analyses' | 'documents' | 'queries'

/**
 * A headline number with its month-on-month movement.
 *
 * `changePercent` is signed: negative renders as a fall — amber, arrow down, since
 * red is the brand colour and cannot also mean "worse". A dashboard that can only
 * show growth is a dashboard nobody trusts.
 */
export type SummaryStat = {
  id: string
  label: string
  value: number
  changePercent: number
  icon: StatIconName
}

/* -------------------------------------------------------------------------- */
/* Projects                                                                   */
/* -------------------------------------------------------------------------- */

/** Where a tender sits in the pipeline. Drives the pill colour and its label. */
export type ProjectStatus = 'in_progress' | 'review' | 'completed' | 'pending'

export type Project = {
  id: string
  name: string
  /** ISO date. Formatted at render time so the locale is the browser's, not the mock's. */
  uploadedAt: string
  status: ProjectStatus
  /** 0-100. The bar and the readout both come from this one number. */
  progress: number
}

/* -------------------------------------------------------------------------- */
/* Activity                                                                   */
/* -------------------------------------------------------------------------- */

export type ActivityKind = 'document' | 'upload' | 'view' | 'query' | 'review'

export type ActivityEntry = {
  id: string
  description: string
  /** ISO timestamp. The feed derives "10 min ago" from it rather than storing prose. */
  occurredAt: string
  kind: ActivityKind
}

/* -------------------------------------------------------------------------- */
/* Analysis chart                                                             */
/* -------------------------------------------------------------------------- */

export type AnalysisPoint = {
  /** ISO date for the tooltip heading. */
  date: string
  /** Short axis label. Only some points are labelled, so this is separate from `date`. */
  label: string
  analyses: number
}

/** The ranges the chart's selector offers. */
export type AnalysisRange = 'this_month' | 'last_month' | 'last_90_days'

/* -------------------------------------------------------------------------- */
/* Storage                                                                    */
/* -------------------------------------------------------------------------- */

export type StorageUsage = {
  usedGb: number
  totalGb: number
}

/* -------------------------------------------------------------------------- */
/* Assistant                                                                  */
/* -------------------------------------------------------------------------- */

/** A canned prompt the assistant panel offers as a chip. */
export type AssistantSuggestion = {
  id: string
  prompt: string
}

/* -------------------------------------------------------------------------- */
/* Quick actions                                                              */
/* -------------------------------------------------------------------------- */

export type QuickActionIconName = 'upload' | 'analysis' | 'search' | 'assistant'

export type QuickAction = {
  id: string
  title: string
  description: string
  icon: QuickActionIconName
  /** Where the card goes. A route path, so the card can be a real link. */
  to: string
}

/* -------------------------------------------------------------------------- */
/* The whole payload                                                          */
/* -------------------------------------------------------------------------- */

/**
 * One object for the whole screen. The page reads this and hands each panel its
 * slice, so there is a single seam to replace when the data becomes real: today a
 * mock import, tomorrow a fetch that resolves to this same shape.
 */
export type DashboardData = {
  stats: SummaryStat[]
  recentProjects: Project[]
  recentActivity: ActivityEntry[]
  analysisSeries: Record<AnalysisRange, AnalysisPoint[]>
  storage: StorageUsage
  assistantSuggestions: AssistantSuggestion[]
  quickActions: QuickAction[]
  unreadNotifications: number
}
