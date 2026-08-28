/**
 * What happened, most recent first, as a timeline.
 *
 * An `<ol>` rather than a `<ul>`: the order carries information — these events
 * happened in this sequence, and reversing the list would state something false.
 *
 * The connector between badges is a `flex-1` element inside each row's icon column,
 * not an absolutely positioned rule offset by a magic number. It therefore always
 * spans exactly the gap between one badge and the next, whether the description
 * wraps to one line or three, and the last row simply omits it.
 *
 * Badges are neutral. Five colours down a narrow column would be a rainbow that
 * encodes nothing a reader can decode — the glyph already says which kind of event
 * this was, and it is the same glyph that kind of event uses everywhere else.
 */

import type { ComponentType } from 'react'
import { ROUTES } from '@/constants/routes'
import { formatRelativeTime } from '@/lib/formatting'
import type { ActivityEntry, ActivityKind } from '@/models/dashboard'
import { Panel } from '@/components/dashboard/Panel'
import { PanelLink } from '@/components/dashboard/PanelLink'
import {
  ActivityIcon,
  CheckCircleIcon,
  EyeIcon,
  FileTextIcon,
  SparklesIcon,
  UploadIcon,
} from '@/components/ui/icons'

const ACTIVITY_ICONS: Record<ActivityKind, ComponentType<{ className?: string }>> = {
  document: FileTextIcon,
  upload: UploadIcon,
  view: EyeIcon,
  query: SparklesIcon,
  review: CheckCircleIcon,
}

function ActivityRow({ entry, isLast }: { entry: ActivityEntry; isLast: boolean }) {
  const Icon = ACTIVITY_ICONS[entry.kind]

  return (
    <li className="flex gap-3.5">
      <div className="flex flex-col items-center">
        <span
          aria-hidden="true"
          className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-hairline bg-surface-muted text-neutral-600"
        >
          <Icon className="size-4" />
        </span>
        {isLast ? null : <span aria-hidden="true" className="mt-1 w-px flex-1 bg-hairline" />}
      </div>

      <div className={isLast ? 'min-w-0 flex-1' : 'min-w-0 flex-1 pb-5'}>
        <p className="text-sm leading-snug text-neutral-800">{entry.description}</p>
        {/* dateTime carries the machine-readable instant; the text carries the
            human one. The two never disagree because both come from occurredAt. */}
        <time dateTime={entry.occurredAt} className="mt-1 block text-xs text-neutral-500">
          {formatRelativeTime(entry.occurredAt)}
        </time>
      </div>
    </li>
  )
}

export function RecentActivity({
  entries,
  className,
}: {
  entries: ActivityEntry[]
  className?: string
}) {
  return (
    <Panel
      title="Recent Activity"
      description="The last few things that happened in your workspace"
      action={<PanelLink to={ROUTES.activity}>View all</PanelLink>}
      className={className}
    >
      {entries.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 py-10 text-center">
          <span
            aria-hidden="true"
            className="flex size-11 items-center justify-center rounded-xl bg-surface-muted text-neutral-500"
          >
            <ActivityIcon className="size-5" />
          </span>
          <p className="text-sm font-medium text-neutral-900">Nothing has happened yet</p>
          <p className="max-w-xs text-xs leading-relaxed text-neutral-500">
            Uploads, analyses and assistant queries all show up here as you work.
          </p>
        </div>
      ) : (
        <ol>
          {entries.map((entry, index) => (
            <ActivityRow
              key={entry.id}
              entry={entry}
              isLast={index === entries.length - 1}
            />
          ))}
        </ol>
      )}
    </Panel>
  )
}
