/**
 * Four ways into the work, in one box.
 *
 * Not four bordered cards inside a bordered panel — that is a card inside a card, and
 * it was costing every action about 40px of horizontal room, which is why the
 * descriptions were wrapping a word per line. One box, four items, and hairlines
 * between them.
 *
 * Those hairlines are the grid's own 1px gaps showing the container's background
 * through: `gap-px bg-hairline` on the grid, `bg-surface` on each item. The pattern is
 * indifferent to the column count, so one column, two, or four all get correct
 * dividers with no per-item border rules and no first/last exceptions.
 *
 * Every card is a real `Link` to a route that exists, because a quick action that does
 * not go anywhere is worse than no quick action — it teaches the reader to stop
 * trusting the panel. The destinations come from the data module, so adding a fifth
 * action is a data change, not a markup change.
 */

import type { ComponentType } from 'react'
import { Link } from 'react-router-dom'
import type { QuickAction, QuickActionIconName } from '@/models/dashboard'
import { Panel } from '@/components/dashboard/Panel'
import { BarChartIcon, SearchIcon, SparklesIcon, UploadIcon } from '@/components/ui/icons'

const ACTION_ICONS: Record<QuickActionIconName, ComponentType<{ className?: string }>> = {
  upload: UploadIcon,
  analysis: BarChartIcon,
  search: SearchIcon,
  assistant: SparklesIcon,
}

function ActionItem({ action }: { action: QuickAction }) {
  const Icon = ACTION_ICONS[action.icon]

  return (
    <Link
      to={action.to}
      className="group flex items-start gap-3.5 bg-surface p-5 transition-colors duration-150 hover:bg-selected"
    >
      <span
        aria-hidden="true"
        className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-surface-muted text-neutral-600 transition-colors duration-150 group-hover:bg-brand-100 group-hover:text-brand-700"
      >
        <Icon className="size-5" />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-neutral-900">{action.title}</span>
        <span className="mt-1 block text-xs leading-relaxed text-neutral-500">
          {action.description}
        </span>
      </span>
    </Link>
  )
}

export function QuickActions({
  actions,
  className,
}: {
  actions: QuickAction[]
  className?: string
}) {
  return (
    /* No description under the title. This bar sits directly beneath the page
       greeting, and a second line of explanatory copy there is one more thing
       between the reader and the numbers. */
    <Panel title="Quick Actions" flush className={className}>
      <div className="grid grid-cols-1 gap-px bg-hairline sm:grid-cols-2 xl:grid-cols-4">
        {actions.map((action) => (
          <ActionItem key={action.id} action={action} />
        ))}
      </div>
    </Panel>
  )
}
