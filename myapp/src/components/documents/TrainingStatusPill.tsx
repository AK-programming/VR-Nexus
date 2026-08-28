/**
 * Where a document has got to in the pipeline, as a chip.
 *
 * The dashboard's `StatusPill` covers four project states and this covers six document
 * ones. Two components rather than one generic pill: they share a shape, not a
 * vocabulary, and a single `Pill` taking `label` and `tone` props would let a caller
 * put a project status on a document row. The shape is copied exactly — same radius,
 * same 11px, same 50-background-with-800-text pairing, which clears 7:1 at every size
 * this renders at.
 *
 * Failed is rose, not brand red, for the reason the whole product avoids it: red is
 * VR-Nexus, and a red chip reads as branding before it reads as trouble. Rose is close
 * enough to carry alarm and far enough not to be mistaken for the logo.
 *
 * The three in-flight stages get a dot that pulses. It is the only moving thing in the
 * table and it answers the one question a reader has about a row that is not finished:
 * whether anything is still happening. `animate-pulse` respects the reduced-motion cap
 * in index.css without needing a second variant here.
 */

import { TRAINING_STATUS_LABELS, isInFlight } from '@/models/documents'
import type { DocumentTrainingStatus } from '@/models/documents'

const STATUS_STYLES: Record<DocumentTrainingStatus, string> = {
  queued: 'border-neutral-200 bg-neutral-100 text-neutral-700',
  parsing: 'border-sky-200 bg-sky-50 text-sky-800',
  tagging: 'border-sky-200 bg-sky-50 text-sky-800',
  embedding: 'border-sky-200 bg-sky-50 text-sky-800',
  indexed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  failed: 'border-rose-200 bg-rose-50 text-rose-800',
}

export function TrainingStatusPill({ status }: { status: DocumentTrainingStatus }) {
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
      {TRAINING_STATUS_LABELS[status]}
    </span>
  )
}
