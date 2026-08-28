/**
 * Which stage an indexing job is on, as a chip.
 *
 * A third pill in this product, and the same argument `TrainingStatusPill` makes for
 * being the second one: these share a shape with the others, not a vocabulary. A job's
 * stages and a document's statuses differ by exactly one value — `complete` against
 * `indexed` — and that one value is the difference between "the run finished" and "the
 * document is searchable". Mapping one onto the other to save a file would put "Ready"
 * on a job row, which describes the document, not the run.
 *
 * Shape, radius, 11px type and the 50-background-with-800-text pairing are copied from
 * `TrainingStatusPill` exactly, so the three read as one family.
 */

import { STAGE_LABELS, isTerminalStage } from '@/models/documents'
import type { JobStage } from '@/models/documents'

const STAGE_STYLES: Record<JobStage, string> = {
  queued: 'border-neutral-200 bg-neutral-100 text-neutral-700',
  parsing: 'border-sky-200 bg-sky-50 text-sky-800',
  tagging: 'border-sky-200 bg-sky-50 text-sky-800',
  embedding: 'border-sky-200 bg-sky-50 text-sky-800',
  complete: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  failed: 'border-rose-200 bg-rose-50 text-rose-800',
}

export function JobStagePill({ stage }: { stage: JobStage }) {
  /* Queued is not terminal but nothing is happening to it either, so it gets no dot.
     The pulse answers "is work being done right now", and for a queued job it is not. */
  const running = !isTerminalStage(stage) && stage !== 'queued'

  return (
    <span
      className={[
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
        'text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap',
        STAGE_STYLES[stage],
      ].join(' ')}
    >
      {running ? (
        <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-current" />
      ) : null}
      {STAGE_LABELS[stage]}
    </span>
  )
}
