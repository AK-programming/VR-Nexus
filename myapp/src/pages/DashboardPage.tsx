/**
 * The dashboard — greeting, quick actions, four headline figures, and two recent
 * lists. Every number here is REAL: it comes from `listTenders` + the library
 * `getStats`, the same seams the rest of the app uses. There is no mock payload
 * any more; the widgets are handed slices built from live data, and where a figure
 * has no month-on-month history the trend chip simply stays hidden rather than
 * showing a fabricated 0%.
 *
 * The trend chart (AnalysisOverview) is intentionally not mounted: the API exposes
 * no time series, and inventing one would be the very mock data this page just
 * dropped. It stays in the codebase for when a real series exists.
 */

import { useMemo } from 'react'
import { ROUTES } from '@/constants/routes'
import {
  formatFirstName,
  formatLongDate,
} from '@/lib/formatting'
import { tenderTitle } from '@/models/tenders'
import type { TenderListItem } from '@/models/tenders'
import { rollUpStats } from '@/models/documents'
import type {
  ActivityEntry,
  Project,
  ProjectStatus,
  QuickAction,
  SummaryStat,
} from '@/models/dashboard'
import { listTenders } from '@/services/tenderService'
import { getStats } from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useAuthStore } from '@/store/authStore'
import { Panel } from '@/components/dashboard/Panel'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { RecentProjects } from '@/components/dashboard/RecentProjects'
import { StatCard } from '@/components/dashboard/StatCard'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'

const QUICK_ACTIONS: QuickAction[] = [
  {
    id: 'upload-tender',
    title: 'Upload a tender',
    description: 'Start a new analysis from a tender PDF.',
    icon: 'analysis',
    to: ROUTES.tenderUpload,
  },
  {
    id: 'add-evidence',
    title: 'Add evidence',
    description: 'Grow your library of case studies and methodology.',
    icon: 'upload',
    to: ROUTES.documentsUpload,
  },
  {
    id: 'ask-assistant',
    title: 'Ask the assistant',
    description: 'Answer a question from your evidence library.',
    icon: 'assistant',
    to: ROUTES.assistant,
  },
  {
    id: 'review-tenders',
    title: 'Review tenders',
    description: 'Open the tenders waiting for your review.',
    icon: 'search',
    to: ROUTES.tenderAnalysis,
  },
]

const DAY_MS = 86_400_000

function greetingFor(hour: number): string {
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

/** Count items whose ISO timestamp at `key` falls in [from, to) days ago. */
function countInWindow(
  items: TenderListItem[],
  key: 'created_at' | 'finalized_at',
  fromDaysAgo: number,
  toDaysAgo: number,
  now: number,
): number {
  const from = now - fromDaysAgo * DAY_MS
  const to = now - toDaysAgo * DAY_MS
  return items.filter((item) => {
    const raw = item[key]
    if (!raw) return false
    const t = new Date(raw).getTime()
    return t >= from && t < to
  }).length
}

/** Whole-percent change of a recent window vs the one before it. 0 means "no trend". */
function pctChange(recent: number, previous: number): number {
  if (previous === 0) return recent > 0 ? 100 : 0
  return Math.round(((recent - previous) / previous) * 100)
}

const STATUS_TO_PROJECT: Record<TenderListItem['status'], ProjectStatus> = {
  uploaded: 'pending',
  parsing: 'in_progress',
  chunking: 'in_progress',
  extracting: 'in_progress',
  merging: 'in_progress',
  matching: 'in_progress',
  reporting: 'in_progress',
  assembling_folder: 'in_progress',
  ready_for_review: 'review',
  finalized: 'completed',
  failed: 'pending',
}

export function DashboardPage() {
  const user = useAuthStore((state) => state.user)

  const data = useAsyncData(
    async (signal) => {
      const [tenders, stats] = await Promise.all([
        listTenders({ limit: 100 }, { signal }),
        getStats({ signal }),
      ])
      return { tenders, stats }
    },
    [],
  )

  const firstName = formatFirstName(user?.name)
  const greeting = greetingFor(new Date().getHours())
  const heading = firstName ? `${greeting}, ${firstName}` : greeting

  const { stats, projects, activity } = useMemo(() => {
    const tenders = data.data?.tenders ?? []
    const now = Date.now()
    const rollup = data.data ? rollUpStats(data.data.stats) : null

    const completed = tenders.filter((t) => t.status === 'finalized').length
    const inReview = tenders.filter((t) => t.status === 'ready_for_review').length

    const statCards: SummaryStat[] = [
      {
        id: 'total-tenders',
        label: 'Total tenders',
        value: tenders.length,
        icon: 'projects',
        changePercent: pctChange(
          countInWindow(tenders, 'created_at', 30, 0, now),
          countInWindow(tenders, 'created_at', 60, 30, now),
        ),
      },
      {
        id: 'completed',
        label: 'Completed',
        value: completed,
        icon: 'analyses',
        changePercent: pctChange(
          countInWindow(tenders, 'finalized_at', 30, 0, now),
          countInWindow(tenders, 'finalized_at', 60, 30, now),
        ),
      },
      {
        id: 'in-review',
        label: 'Needs review',
        value: inReview,
        icon: 'queries',
        changePercent: 0,
      },
      {
        id: 'library-docs',
        label: 'Library documents',
        value: rollup?.total ?? 0,
        icon: 'documents',
        changePercent: 0,
      },
    ]

    const recentProjects: Project[] = [...tenders]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .slice(0, 6)
      .map((t) => ({
        id: t.id,
        name: tenderTitle(t),
        uploadedAt: t.created_at,
        status: STATUS_TO_PROJECT[t.status],
        progress: t.progress_percent,
      }))

    const recentActivity: ActivityEntry[] = tenders
      .flatMap<ActivityEntry>((t) => {
        const events: ActivityEntry[] = [
          {
            id: `up-${t.id}`,
            description: `Tender uploaded - ${tenderTitle(t)}`,
            occurredAt: t.created_at,
            kind: 'upload',
          },
        ]
        if (t.finalized_at) {
          events.push({
            id: `fin-${t.id}`,
            description: `Tender finalized - ${tenderTitle(t)}`,
            occurredAt: t.finalized_at,
            kind: 'review',
          })
        }
        return events
      })
      .sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))
      .slice(0, 6)

    return { stats: statCards, projects: recentProjects, activity: recentActivity }
  }, [data.data])

  return (
    <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
      <header className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            {heading}
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Here is where every tender in your workspace stands today.
          </p>
        </div>
        <p className="hidden shrink-0 text-sm text-neutral-500 sm:block">
          {formatLongDate(new Date().toISOString())}
        </p>
      </header>

      <QuickActions actions={QUICK_ACTIONS} />

      {data.status === 'error' && data.data === null ? (
        <Panel title="Overview">
          <ErrorBlock
            title="The dashboard could not be loaded"
            message={data.error ?? 'The request did not complete.'}
            offline={data.offline}
            onRetry={data.refetch}
          />
        </Panel>
      ) : data.status === 'loading' && data.data === null ? (
        <Panel title="Overview" description="Reading your workspace.">
          <LoadingRows rows={4} label="Loading the dashboard" />
        </Panel>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map((stat) => (
              <StatCard key={stat.id} stat={stat} />
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-12">
            <RecentProjects projects={projects} className="xl:col-span-7" />
            <RecentActivity entries={activity} className="xl:col-span-5" />
          </div>
        </>
      )}
    </div>
  )
}
