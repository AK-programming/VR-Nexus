/**
 * The dashboard. Five sections, top to bottom, in the order the work happens.
 *
 * The order is the point. Actions first, because the reason to open a dashboard is
 * usually to do something rather than to read it. Then the four figures that say
 * whether anything needs attention. Then the trend, full width, because a 31-point
 * series in a five-twelfths column is a sparkline pretending to be a chart. Then the
 * two lists that answer "what happened" side by side.
 *
 * This page is the only file that touches `DASHBOARD_DATA`. Each panel is handed the
 * slice it needs, so replacing the mock with a fetch is a change to the first few
 * lines of this component and nothing else — no panel knows where its data came from.
 *
 * The page also owns all grid placement. Panels never position themselves; they take
 * a `className` and let this file decide where they sit. That is what keeps the
 * layout readable in one place instead of spread across the components.
 *
 * `AiAssistantPanel` and `StorageMeter` are built and still in the project; they are
 * simply not mounted here. Either goes back on the page as one line.
 */

import { DASHBOARD_DATA } from '@/mocks/dashboard'
import { formatFirstName, formatLongDate } from '@/lib/formatting'
import { useAuthStore } from '@/store/authStore'
import { AnalysisOverview } from '@/components/dashboard/AnalysisOverview'
import { QuickActions } from '@/components/dashboard/QuickActions'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { RecentProjects } from '@/components/dashboard/RecentProjects'
import { StatCard } from '@/components/dashboard/StatCard'

/** Local because it is page copy, not data formatting. */
function greetingFor(hour: number): string {
  if (hour < 12) {
    return 'Good morning'
  }
  if (hour < 17) {
    return 'Good afternoon'
  }
  return 'Good evening'
}

export function DashboardPage() {
  const user = useAuthStore((state) => state.user)

  const firstName = formatFirstName(user?.name)
  const greeting = greetingFor(new Date().getHours())
  const heading = firstName ? `${greeting}, ${firstName}` : greeting

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
        {/* Hidden on a phone: the date is orientation, not information, and it is
            the first thing worth giving up when the width runs out. */}
        <p className="hidden shrink-0 text-sm text-neutral-500 sm:block">
          {formatLongDate(new Date().toISOString())}
        </p>
      </header>

      {/* Full width, and no grid wrapper — the panel is the row. The four actions
          divide themselves inside it. */}
      <QuickActions actions={DASHBOARD_DATA.quickActions} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {DASHBOARD_DATA.stats.map((stat) => (
          <StatCard key={stat.id} stat={stat} />
        ))}
      </div>

      <AnalysisOverview series={DASHBOARD_DATA.analysisSeries} />

      {/* The only split row left. Projects take the wider side: each row carries a
          name, a date, a status and a progress bar, where an activity entry carries
          one line and a timestamp. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-12">
        <RecentProjects projects={DASHBOARD_DATA.recentProjects} className="xl:col-span-7" />
        <RecentActivity entries={DASHBOARD_DATA.recentActivity} className="xl:col-span-5" />
      </div>
    </div>
  )
}
