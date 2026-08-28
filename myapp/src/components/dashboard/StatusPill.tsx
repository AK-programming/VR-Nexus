/**
 * Where a tender sits in the pipeline, as a bordered chip.
 *
 * Four states, four hues, and none of them brand red — red is the product's own
 * colour and a red status would read as "VR-Nexus" before it read as "attention".
 * Every pairing is a 50-weight background with an 800-weight label, which clears
 * 7:1 in all four cases, because these chips are 11px and small text has the least
 * margin for error of anything on the page.
 *
 * The label is written out rather than derived from the status string. "in_progress"
 * would prettify to "In progress" and the house style is "In Progress"; guessing at
 * capitalisation is not worth saving four lines.
 */

import type { ProjectStatus } from '@/models/dashboard'

const STATUS_STYLES: Record<ProjectStatus, { label: string; className: string }> = {
  in_progress: {
    label: 'In Progress',
    className: 'border-sky-200 bg-sky-50 text-sky-800',
  },
  review: {
    label: 'In Review',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
  },
  completed: {
    label: 'Completed',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  },
  pending: {
    label: 'Pending',
    className: 'border-neutral-200 bg-neutral-100 text-neutral-700',
  },
}

export function StatusPill({ status }: { status: ProjectStatus }) {
  const { label, className } = STATUS_STYLES[status]

  return (
    <span
      className={[
        'inline-flex shrink-0 items-center rounded-full border px-2.5 py-1',
        'text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap',
        className,
      ].join(' ')}
    >
      {label}
    </span>
  )
}
