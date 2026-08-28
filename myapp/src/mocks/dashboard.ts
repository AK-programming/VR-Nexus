/**
 * The dashboard's data, standing in for an API that does not exist yet.
 *
 * This is the only seam between the screen and its numbers. Every panel takes its
 * slice as a prop, so when the endpoints land the change is a fetch that resolves
 * to `DashboardData` and this file gets deleted — no panel is touched.
 *
 * The figures are the ones from the approved mockup, kept verbatim so the built
 * page can be compared against it side by side.
 */

import { ROUTES } from '@/constants/routes'
import type {
  ActivityEntry,
  AnalysisPoint,
  AnalysisRange,
  AssistantSuggestion,
  DashboardData,
  Project,
  QuickAction,
  SummaryStat,
} from '@/models/dashboard'

/* -------------------------------------------------------------------------- */
/* Time helpers                                                               */
/* -------------------------------------------------------------------------- */

/*
 * The activity feed is anchored to the moment the module is imported rather than
 * to fixed dates in 2025. A hard-coded timestamp would render as "1 year ago" and
 * make a working feed look broken. The values are frozen at import, so the feed
 * still ages correctly while the tab is open — after an hour, "10 min ago" becomes
 * "1 hour ago", which is exactly what real data would do.
 */
const IMPORTED_AT = Date.now()

function minutesAgo(minutes: number): string {
  return new Date(IMPORTED_AT - minutes * 60_000).toISOString()
}

function hoursAgo(hours: number): string {
  return minutesAgo(hours * 60)
}

const MONTH_LABELS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const

/**
 * Turns a run of daily counts into chart points.
 *
 * Noon UTC rather than midnight: midnight UTC is the previous evening anywhere
 * west of Greenwich, so a point labelled "16 May" would format as 15 May for a
 * reader in New York. Noon has no timezone that can move it off its own day.
 */
function buildDailySeries(year: number, monthIndex: number, counts: number[]): AnalysisPoint[] {
  return counts.map((analyses, index) => {
    const day = index + 1

    return {
      date: new Date(Date.UTC(year, monthIndex, day, 12)).toISOString(),
      label: `${day} ${MONTH_LABELS[monthIndex]}`,
      analyses,
    }
  })
}

/* -------------------------------------------------------------------------- */
/* Summary tiles                                                              */
/* -------------------------------------------------------------------------- */

const stats: SummaryStat[] = [
  { id: 'projects', label: 'Total Projects', value: 24, changePercent: 20, icon: 'projects' },
  { id: 'analyses', label: 'Analyses Completed', value: 16, changePercent: 18, icon: 'analyses' },
  { id: 'documents', label: 'Documents', value: 2341, changePercent: 16, icon: 'documents' },
  { id: 'queries', label: 'AI Queries', value: 1028, changePercent: 11, icon: 'queries' },
]

/* -------------------------------------------------------------------------- */
/* Projects                                                                   */
/* -------------------------------------------------------------------------- */

const recentProjects: Project[] = [
  {
    id: 'wasa-rawalpindi',
    name: 'WASA Rawalpindi Water Supply System',
    uploadedAt: '2025-05-15T12:00:00.000Z',
    status: 'in_progress',
    progress: 65,
  },
  {
    id: 'dha-office-complex',
    name: 'DHA Office Complex Construction',
    uploadedAt: '2025-05-10T12:00:00.000Z',
    status: 'review',
    progress: 80,
  },
  {
    id: 'pepco-supply',
    name: 'PEPCO Supply Tender',
    uploadedAt: '2025-05-06T12:00:00.000Z',
    status: 'completed',
    progress: 100,
  },
  {
    id: 'cda-development',
    name: 'CDA Development Project',
    uploadedAt: '2025-05-02T12:00:00.000Z',
    status: 'in_progress',
    progress: 30,
  },
  {
    id: 'metrology-lab',
    name: 'Metrology Lab Setup',
    uploadedAt: '2025-04-28T12:00:00.000Z',
    status: 'pending',
    progress: 10,
  },
]

/* -------------------------------------------------------------------------- */
/* Activity                                                                   */
/* -------------------------------------------------------------------------- */

const recentActivity: ActivityEntry[] = [
  {
    id: 'act-1',
    description: 'Tender document “WASA Tender.pdf” analysed',
    occurredAt: minutesAgo(10),
    kind: 'document',
  },
  {
    id: 'act-2',
    description: 'Case study “DHA Office Complex” uploaded',
    occurredAt: minutesAgo(25),
    kind: 'upload',
  },
  {
    id: 'act-3',
    description: 'Methodology document viewed',
    occurredAt: hoursAgo(1),
    kind: 'view',
  },
  {
    id: 'act-4',
    description: 'AI Assistant query executed',
    occurredAt: hoursAgo(2),
    kind: 'query',
  },
  {
    id: 'act-5',
    description: 'Evidence review completed',
    occurredAt: hoursAgo(3),
    kind: 'review',
  },
]

/* -------------------------------------------------------------------------- */
/* Analysis chart                                                             */
/* -------------------------------------------------------------------------- */

/* May 2025, day by day. The peak of 28 on the 16th is the point the mockup
   highlights, so it is preserved exactly. */
const MAY_2025 = [
  2, 3, 3, 5, 6, 6, 9, 11, 13, 15, 18, 20, 19, 17, 22, 28, 25, 22, 20, 19, 21, 20, 19, 22, 24, 23,
  26, 28, 31, 33, 35,
]

/* April 2025. Flatter and lower — the month before the platform got busy. */
const APRIL_2025 = [
  4, 5, 7, 6, 9, 11, 10, 13, 12, 14, 16, 15, 18, 17, 19, 21, 20, 18, 22, 24, 23, 25, 22, 21, 24, 26,
  25, 27, 26, 24,
]

/* Ninety days is too many points to read as a daily line, so this range is
   weekly totals. Same shape, one thirteenth of the noise. */
const LAST_90_DAYS: AnalysisPoint[] = [
  { date: '2025-03-03T12:00:00.000Z', label: '3 Mar', analyses: 42 },
  { date: '2025-03-10T12:00:00.000Z', label: '10 Mar', analyses: 51 },
  { date: '2025-03-17T12:00:00.000Z', label: '17 Mar', analyses: 58 },
  { date: '2025-03-24T12:00:00.000Z', label: '24 Mar', analyses: 55 },
  { date: '2025-03-31T12:00:00.000Z', label: '31 Mar', analyses: 68 },
  { date: '2025-04-07T12:00:00.000Z', label: '7 Apr', analyses: 76 },
  { date: '2025-04-14T12:00:00.000Z', label: '14 Apr', analyses: 84 },
  { date: '2025-04-21T12:00:00.000Z', label: '21 Apr', analyses: 97 },
  { date: '2025-04-28T12:00:00.000Z', label: '28 Apr', analyses: 105 },
  { date: '2025-05-05T12:00:00.000Z', label: '5 May', analyses: 118 },
  { date: '2025-05-12T12:00:00.000Z', label: '12 May', analyses: 134 },
  { date: '2025-05-19T12:00:00.000Z', label: '19 May', analyses: 152 },
  { date: '2025-05-26T12:00:00.000Z', label: '26 May', analyses: 168 },
]

const analysisSeries: Record<AnalysisRange, AnalysisPoint[]> = {
  this_month: buildDailySeries(2025, 4, MAY_2025),
  last_month: buildDailySeries(2025, 3, APRIL_2025),
  last_90_days: LAST_90_DAYS,
}

/* -------------------------------------------------------------------------- */
/* Assistant                                                                  */
/* -------------------------------------------------------------------------- */

const assistantSuggestions: AssistantSuggestion[] = [
  { id: 'summarise', prompt: 'Summarise this tender' },
  { id: 'similar', prompt: 'Find similar case studies' },
  { id: 'requirements', prompt: 'Extract key requirements' },
  { id: 'missing', prompt: 'What documents are missing?' },
]

/* -------------------------------------------------------------------------- */
/* Quick actions                                                              */
/* -------------------------------------------------------------------------- */

const quickActions: QuickAction[] = [
  {
    id: 'upload',
    title: 'Upload Document',
    description: 'Upload tender or company documents',
    icon: 'upload',
    to: ROUTES.documents,
  },
  {
    id: 'analyse',
    title: 'Start New Analysis',
    description: 'Analyse a new tender document',
    icon: 'analysis',
    to: ROUTES.tenderAnalysis,
  },
  {
    id: 'search',
    title: 'Search Documents',
    description: 'Find documents in your workspace',
    icon: 'search',
    to: ROUTES.documents,
  },
  {
    id: 'assistant',
    title: 'AI Assistant',
    description: 'Ask anything about tenders & documents',
    icon: 'assistant',
    to: ROUTES.assistant,
  },
]

/* -------------------------------------------------------------------------- */
/* The whole payload                                                          */
/* -------------------------------------------------------------------------- */

export const DASHBOARD_DATA: DashboardData = {
  stats,
  recentProjects,
  recentActivity,
  analysisSeries,
  storage: { usedGb: 13, totalGb: 20 },
  assistantSuggestions,
  quickActions,
  unreadNotifications: 3,
}
