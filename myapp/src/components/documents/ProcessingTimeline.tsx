/**
 * The stage track for one indexing job.
 *
 * Five nodes, and only five: `queued → parsing → tagging → embedding → complete`, which
 * is exactly what `JobStage` can emit. The mockup shows "Splitting into Chunks" and
 * "Indexing" as separate steps, and there is no backend stage behind either — drawn
 * here they would be two boxes that never light up on any job, which is a worse lie
 * than leaving them out. `failed` is not a sixth node for the same reason in reverse:
 * it is what happens *instead of* a step, so it is rendered by marking the step that
 * stopped. See `STAGE_SEQUENCE` in the model for the full argument.
 *
 * Two orientations, one set of markup. Below `md` the track runs down the left edge
 * with the label beside each node, which is the only thing that fits at 375px. From
 * `md` it runs across, as the screenshot shows. The connectors are the only part that
 * differs: the vertical one is drawn per node, so it stretches with whatever height the
 * text takes, and the horizontal one is a single bar behind all five, positioned from
 * the first dot's centre to the last so it cannot overshoot the ends.
 *
 * Colour follows the status pills rather than the brand: emerald for a stage that
 * finished, sky for the one running, neutral for one not started, rose for the one that
 * failed. The percentage bar underneath is brand red, matching the progress bars on the
 * dashboard — a proportion is not a state, and the two want different colours.
 */

import {
  STAGE_DESCRIPTIONS,
  STAGE_LABELS,
  STAGE_SEQUENCE,
  stageStates,
} from '@/models/documents'
import type { JobStage, StageState, TimelineStage } from '@/models/documents'
import { CheckIcon, CloseIcon, SpinnerIcon } from '@/components/ui/icons'

/** How each node paints. Kept as one table so a state cannot be styled two ways. */
const NODE_STYLES: Record<StageState, string> = {
  done: 'border-emerald-300 bg-emerald-500 text-white',
  active: 'border-sky-300 bg-sky-500 text-white',
  pending: 'border-hairline bg-surface text-neutral-400',
  failed: 'border-rose-300 bg-rose-500 text-white',
}

const LABEL_STYLES: Record<StageState, string> = {
  done: 'text-neutral-900',
  active: 'text-sky-800',
  pending: 'text-neutral-500',
  failed: 'text-rose-800',
}

/** What a screen reader hears instead of the colour it cannot see. */
const STATE_NAMES: Record<StageState, string> = {
  done: 'completed',
  active: 'in progress',
  pending: 'not started',
  failed: 'failed',
}

function NodeMark({ state }: { state: StageState }) {
  if (state === 'done') {
    return <CheckIcon className="size-3.5" />
  }

  if (state === 'active') {
    return <SpinnerIcon className="size-3.5 animate-spin" />
  }

  if (state === 'failed') {
    return <CloseIcon className="size-3.5" />
  }

  return <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
}

type ProcessingTimelineProps = {
  stage: JobStage
  /** Which step a failed job stopped on, when it is known. */
  failedAt?: TimelineStage
  /** 0-100, as the worker last reported it. */
  progress: number
  /** The worker's own wording. Shown verbatim; it is more specific than anything here. */
  message?: string | null
}

export function ProcessingTimeline({
  stage,
  failedAt,
  progress,
  message,
}: ProcessingTimelineProps) {
  const states = stageStates(stage, failedAt)
  const nodeCount = STAGE_SEQUENCE.length

  /*
   * How far the connector is filled: up to and including the last node that finished.
   * The first node that is not `done` is where the track stops — and when every node is
   * done the fill runs the whole way.
   */
  const firstUnfinished = STAGE_SEQUENCE.findIndex((value) => states[value] !== 'done')
  const reachedIndex = firstUnfinished === -1 ? nodeCount - 1 : firstUnfinished
  const fillPercent = (reachedIndex / (nodeCount - 1)) * 100

  /* Half a node's share of the row, which is where the first and last dots sit. */
  const trackInset = `${100 / (nodeCount * 2)}%`

  /** The line to read under the track: what is happening, and what the worker said. */
  const currentStage: TimelineStage | undefined =
    stage === 'failed'
      ? failedAt
      : (STAGE_SEQUENCE as readonly string[]).includes(stage)
        ? (stage as TimelineStage)
        : undefined

  return (
    <div>
      <ol className="relative flex flex-col md:flex-row">
        {/* The horizontal rail, behind the nodes. One element rather than four, so the
            line has no seams where the segments meet. */}
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-[13px] hidden h-0.5 rounded-full bg-hairline md:block"
          style={{ left: trackInset, right: trackInset }}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute top-[13px] hidden h-0.5 rounded-full bg-emerald-500 transition-[width] duration-300 md:block"
          style={{ left: trackInset, width: `calc((100% - ${trackInset} * 2) * ${fillPercent / 100})` }}
        />

        {STAGE_SEQUENCE.map((value, index) => {
          const state = states[value]
          const isLast = index === nodeCount - 1

          return (
            <li
              key={value}
              className="relative flex min-w-0 gap-3.5 pb-6 last:pb-0 md:flex-1 md:flex-col md:items-center md:gap-2 md:pb-0 md:text-center"
            >
              {/* The vertical connector, one per node except the last. Anchored under
                  its own dot and run to the bottom of the item, so it meets the next
                  dot no matter how tall the label wraps. */}
              {!isLast ? (
                <span
                  aria-hidden="true"
                  className={[
                    'absolute top-8 left-[13px] bottom-0 w-0.5 rounded-full md:hidden',
                    state === 'done' ? 'bg-emerald-500' : 'bg-hairline',
                  ].join(' ')}
                />
              ) : null}

              <span
                className={[
                  'relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border-2',
                  'transition-colors duration-300',
                  NODE_STYLES[state],
                ].join(' ')}
              >
                <NodeMark state={state} />
              </span>

              <div className="min-w-0 md:w-full">
                <p
                  className={[
                    'text-xs font-semibold tracking-tight md:text-[0.8125rem]',
                    LABEL_STYLES[state],
                  ].join(' ')}
                >
                  {STAGE_LABELS[value]}
                  <span className="sr-only"> - {STATE_NAMES[state]}</span>
                </p>
                {/* The description belongs to the node on a phone, where there is a
                    column of room beside it. On a five-across row there is not, and it
                    moves to the single status line below the track. */}
                <p className="mt-0.5 text-xs leading-relaxed text-neutral-500 md:hidden">
                  {STAGE_DESCRIPTIONS[value]}
                </p>
              </div>
            </li>
          )
        })}
      </ol>

      <div className="mt-6 flex flex-col gap-2 border-t border-hairline pt-4 sm:flex-row sm:items-center sm:gap-5">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span
            aria-hidden="true"
            className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-neutral-200"
          >
            <span
              className={[
                'block h-full rounded-full transition-[width] duration-300',
                stage === 'failed' ? 'bg-rose-500' : 'bg-brand-500',
              ].join(' ')}
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </span>
          <span className="w-10 shrink-0 text-right text-xs font-semibold text-neutral-700 tabular-nums">
            {Math.round(progress)}%
          </span>
        </div>

        {/* aria-live because this is the only part of the page that changes on its own
            while a job runs — a reader who is not watching the dots still hears it. */}
        <p
          aria-live="polite"
          className="min-w-0 text-xs leading-relaxed text-neutral-600 sm:max-w-md sm:flex-1 sm:text-right"
        >
          {message ??
            (currentStage ? STAGE_DESCRIPTIONS[currentStage] : 'Nothing reported yet.')}
        </p>
      </div>
    </div>
  )
}
