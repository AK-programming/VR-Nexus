/**
 * Where a tender has got to in the pipeline, as a chip.
 *
 * A sibling of the documents `TrainingStatusPill` and the dashboard `StatusPill`,
 * and a third component rather than a shared generic one for the reason spelled
 * out on those two: they share a shape, not a vocabulary. A tender moves through
 * eleven states, a document through six, a project through four; one `Pill` taking
 * `label` and `tone` would happily let a caller put a tender status on a document
 * row. The visual shape is copied exactly — same radius, same 11px, same
 * 50-background / 800-text pairing, which clears 7:1 at every size this renders at.
 *
 * The colour tells the reader the *kind* of state at a glance:
 *   • neutral  — uploaded, sitting in the queue before work starts
 *   • sky      — one of the seven working stages, actively running
 *   • amber    — ready for review: finished analysing, now waiting on a human
 *   • emerald  — finalized: reviewed, locked in, output assembled
 *   • rose     — failed
 *
 * Rose, not brand red, for failure — the whole product avoids red chips because
 * red is VR-Nexus, and a red chip reads as branding before it reads as trouble.
 *
 * The eight in-flight stages (`isInFlight`) get a dot that pulses — the one moving
 * thing in a table row, answering the only question a reader has about an
 * unfinished row: whether anything is still happening. `ready_for_review` is
 * settled, not in flight, so it holds still; `animate-pulse` respects the
 * reduced-motion cap in index.css without a second variant here.
 */

import { TENDER_STATUS_LABELS, isInFlight } from '@/models/tenders'
import type { TenderStatus } from '@/models/tenders'

const STATUS_STYLES: Record<TenderStatus, string> = {
  uploaded: 'border-neutral-200 bg-neutral-100 text-neutral-700',
  parsing: 'border-sky-200 bg-sky-50 text-sky-800',
  chunking: 'border-sky-200 bg-sky-50 text-sky-800',
  extracting: 'border-sky-200 bg-sky-50 text-sky-800',
  merging: 'border-sky-200 bg-sky-50 text-sky-800',
  matching: 'border-sky-200 bg-sky-50 text-sky-800',
  reporting: 'border-sky-200 bg-sky-50 text-sky-800',
  assembling_folder: 'border-sky-200 bg-sky-50 text-sky-800',
  ready_for_review: 'border-amber-200 bg-amber-50 text-amber-800',
  finalized: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  failed: 'border-rose-200 bg-rose-50 text-rose-800',
}

export function TenderStatusPill({ status }: { status: TenderStatus }) {
  const running = isInFlight(status)

  return (
    <span
      className={[
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
        'text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap',
        STATUS_STYLES[status],
      ].join(' ')}
    >
      {running ? (
        <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-current" />
      ) : null}
      {TENDER_STATUS_LABELS[status]}
    </span>
  )
}
