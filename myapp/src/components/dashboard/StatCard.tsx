/**
 * A headline number, its month-on-month movement, and a glyph.
 *
 * On the trend colour: a rise is emerald and a fall is amber, not red. In this
 * product red *is* the brand — it is the logo, the primary button and the active
 * navigation marker — so red cannot also mean "this got worse" without the two
 * meanings blurring. Amber is the conventional attention colour and collides with
 * nothing else on the page.
 *
 * The arrow is the redundant channel. Anyone who cannot separate the emerald from
 * the amber still gets the direction from the glyph and the sign in the number.
 */

import type { ComponentType } from 'react'
import { formatCount, formatSignedPercent } from '@/lib/formatting'
import type { StatIconName, SummaryStat } from '@/models/dashboard'
import { ArrowDownIcon, ArrowUpIcon, BarChartIcon, ChatIcon, FileTextIcon, FolderIcon } from '@/components/ui/icons'

/*
 * The data module names its glyph; this maps the name to a component. That
 * indirection is the reason `src/mocks/dashboard.ts` never has to import React,
 * and the reason a real API can send the same string.
 */
const STAT_ICONS: Record<StatIconName, ComponentType<{ className?: string }>> = {
  projects: FolderIcon,
  analyses: BarChartIcon,
  documents: FileTextIcon,
  queries: ChatIcon,
}

export function StatCard({ stat }: { stat: SummaryStat }) {
  const Icon = STAT_ICONS[stat.icon]
  const isRise = stat.changePercent >= 0
  const TrendIcon = isRise ? ArrowUpIcon : ArrowDownIcon

  return (
    <div className="flex flex-col rounded-2xl border border-hairline bg-surface p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-neutral-500">{stat.label}</p>
        <span
          aria-hidden="true"
          className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600"
        >
          <Icon className="size-5" />
        </span>
      </div>

      {/* tabular-nums so a column of four figures lines up on the digit rather
          than drifting with the width of a 1 against a 4. */}
      <p className="mt-4 font-display text-3xl font-semibold tracking-tight text-neutral-900 tabular-nums">
        {formatCount(stat.value)}
      </p>

      {/* Only shown when there is a real movement to report; a flat 0% would read
          as a fabricated trend on data that has no month-on-month history yet. */}
      {stat.changePercent !== 0 ? (
        <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span
            className={[
              'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-semibold tabular-nums',
              isRise ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700',
            ].join(' ')}
          >
            <TrendIcon className="size-3.5" />
            {formatSignedPercent(stat.changePercent)}
          </span>
          <span className="text-xs text-neutral-500">vs last month</span>
        </p>
      ) : null}
    </div>
  )
}
