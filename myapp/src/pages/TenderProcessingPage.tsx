/**
 * What the tender pipeline is doing right now.
 *
 * A sibling of the documents `ProcessingPage`, and the same two-part shape — one
 * run in focus with the full track, the rest a glanceable list beside it — but the
 * tender case is simpler in three ways that all come from the backend, not from
 * taste:
 *
 *   **No job/document split.** A library document and its index job are two rows,
 *   which is why that page pairs them and has to reason about a document with no
 *   job. A tender *is* the unit of work: it carries its own status and percent, so
 *   the queue here is just tenders, straight from `listTenders`.
 *
 *   **Nothing is ever "not started".** A document is born `queued` and sits there
 *   until a person presses Index. A tender is born `uploaded` and the upload call
 *   enqueues the pipeline in the same breath, so there is no limbo to represent and
 *   no Index button to offer — every tender in this list is already moving, already
 *   finished, or has failed.
 *
 *   **This page does not mutate.** The library page can start work (train). Here the
 *   only actions are watch, reconnect, and open — finalizing a reviewed tender is a
 *   decision made on the tender's own page, after reading the requirements and
 *   coverage, not a button on a progress screen. So there is no busy state and no
 *   notice: the page reads, and hands off.
 *
 * The queue is every tender that is **not yet finalized** — the eight working
 * stages, the ones that failed, and the ones sitting at `ready_for_review` waiting
 * for a person. A finalized tender has left the pipeline for good and lives in the
 * Overview list, exactly as an `indexed` document leaves the library's queue.
 *
 * `?tender=` in the URL is what Upload navigates to after starting a run, so
 * "upload it, then watch it" is one motion. An unknown id falls back to the top of
 * the list rather than erroring — a link ages out when its tender finalizes, and a
 * stale link should still land somewhere useful.
 *
 * Connection state is shown, not hidden: a timeline that has quietly stopped
 * updating is indistinguishable from a stuck run, and which one it is is the only
 * thing the reader needs. `live` is the socket, `polling` the 2s fallback, `offline`
 * means nothing on screen is current. See `useTenderProgress` for how it falls back.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ROUTES, tenderDetailPath } from '@/constants/routes'
import { isInFlight, isSettled, progressFromDetail, tenderTitle } from '@/models/tenders'
import type { TenderListItem } from '@/models/tenders'
import { listTenders } from '@/services/tenderService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useTenderProgress } from '@/hooks/useTenderProgress'
import type { TenderConnection } from '@/hooks/useTenderProgress'
import { formatCount, formatRelativeTime } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { ErrorBlock, LoadingRows, StaleDataNotice } from '@/components/feedback/DataState'
import { TenderTimeline } from '@/components/tender/TenderTimeline'
import { TenderStatusPill } from '@/components/tender/TenderStatusPill'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { TableEmptyState } from '@/components/ui/DataTable'
import {
  ActivityIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  RefreshIcon,
  SignalOffIcon,
  UploadIcon,
} from '@/components/ui/icons'

/* In-flight tenders are always among the most recent, so a bounded recent window
   holds the whole live queue without a dedicated endpoint. */
const QUEUE_LIMIT = 100

/** How each connection state is worded and painted. Mirrors the library page's set. */
const CONNECTION_NOTES: Record<TenderConnection, { label: string; classes: string }> = {
  idle: { label: 'Connecting', classes: 'border-neutral-200 bg-neutral-100 text-neutral-700' },
  live: { label: 'Live', classes: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  polling: { label: 'Polling every 2s', classes: 'border-sky-200 bg-sky-50 text-sky-800' },
  offline: { label: 'Service unreachable', classes: 'border-amber-200 bg-amber-50 text-amber-900' },
  closed: { label: 'Finished', classes: 'border-neutral-200 bg-neutral-100 text-neutral-700' },
}

/**
 * Where a tender sorts in the queue. Lower rises.
 *
 * Work in flight first — that is what someone opening this page came to watch.
 * Failures next, the only rows that force a decision with no happy path. Tenders
 * ready for review last of the three: they are a decision too, but a welcome one
 * that can wait. Finalized tenders are filtered out before this runs.
 */
function tenderRank(tender: TenderListItem): number {
  if (isInFlight(tender.status)) {
    return 0
  }
  if (tender.status === 'failed') {
    return 1
  }
  return 2
}

function ConnectionNote({ connection }: { connection: TenderConnection }) {
  const note = CONNECTION_NOTES[connection]

  return (
    <span
      className={[
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1',
        'text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap',
        note.classes,
      ].join(' ')}
    >
      {connection === 'live' || connection === 'polling' ? (
        <span aria-hidden="true" className="size-1.5 animate-pulse rounded-full bg-current" />
      ) : null}
      {note.label}
    </span>
  )
}

/**
 * The focused tender's live view.
 *
 * A separate component so the parent can remount it with a `key`, which is what
 * Reconnect does: the socket-and-poll lifecycle lives in one effect keyed on the
 * tender id, so the honest way to start over is a fresh instance rather than a
 * `retry()` that unpicks the teardown by hand.
 *
 * Seeded from the list row via `progressFromDetail` so it renders the last known
 * state before the socket connects — the list carries no `progress_message`, so
 * that starts null and the first frame or poll fills it in.
 */
function TenderWatcher({
  tender,
  onRetry,
  onFinished,
}: {
  tender: TenderListItem
  onRetry: () => void
  onFinished: () => void
}) {
  const seed = progressFromDetail({
    status: tender.status,
    progress_percent: tender.progress_percent,
    progress_message: null,
    extracted_requirements_count: tender.extracted_requirements_count,
  })

  const { progress, failedAt, connection } = useTenderProgress(tender.id, { initialProgress: seed })
  const current = progress ?? seed

  /*
   * Seeded with whether the tender was already settled when this mounted, so opening
   * a long-finished tender does not fire a pointless refetch. Only a transition into
   * a settled state counts — that is the moment the row's status changes on the
   * server and the queue beside this panel goes stale. The ref also makes it fire
   * once rather than on every subsequent frame.
   */
  const settledRef = useRef(isSettled(tender.status))

  useEffect(() => {
    if (settledRef.current || !isSettled(current.status)) {
      return
    }

    settledRef.current = true
    onFinished()
  }, [current.status, onFinished])

  const ready = current.status === 'ready_for_review'
  const requirementCount = current.extractedRequirementsCount

  return (
    <Panel
      title={tenderTitle(tender)}
      description={
        current.updatedAt
          ? `${current.stepLabel} · updated ${formatRelativeTime(current.updatedAt)}`
          : current.stepLabel
      }
      action={<ConnectionNote connection={connection} />}
    >
      <div className="flex flex-col gap-5">
        <TenderTimeline
          status={current.status}
          failedAt={failedAt}
          progress={current.percent}
          message={current.message}
        />

        {/* The one tangible number the pipeline produces as it runs. Shown once
            extraction has found anything, and it stays visible afterwards as a record
            of how much the tender held. */}
        {typeof requirementCount === 'number' && requirementCount > 0 ? (
          <p className="text-xs text-neutral-500">
            <span className="font-semibold text-neutral-700 tabular-nums">
              {formatCount(requirementCount)}
            </span>{' '}
            {requirementCount === 1 ? 'requirement' : 'requirements'} extracted so far.
          </p>
        ) : null}

        {/* Ready for review is the payoff, so it gets its own block and the primary
            action below — the marked rail says the run finished, this says what to do. */}
        {ready ? (
          <AlertMessage tone="success" title="Analysis complete">
            VR-Nexus has read the tender and matched it against your evidence. Review the
            requirements and coverage, then finalize to lock in the output folder.
          </AlertMessage>
        ) : null}

        {current.status === 'failed' ? (
          <AlertMessage tone="warning" title="This tender was not analysed">
            {current.message ||
              'The pipeline stopped before the analysis finished. Check that the source PDF is readable, or upload the tender again.'}
          </AlertMessage>
        ) : null}

        {connection === 'offline' ? (
          <AlertMessage tone="neutral" icon={<SignalOffIcon />} title="Progress is not updating">
            The analysis service is not reachable, so what is shown is the last state on
            record. This panel refreshes itself as soon as the service answers.
          </AlertMessage>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="truncate text-xs text-neutral-500">{tender.original_filename}</p>

          <div className="flex flex-wrap gap-2">
            <ActionButton
              variant="secondary"
              size="sm"
              leadingIcon={<RefreshIcon />}
              onClick={onRetry}
            >
              Reconnect
            </ActionButton>
            <ActionButton
              variant={ready ? 'primary' : 'secondary'}
              size="sm"
              to={tenderDetailPath(tender.id)}
              trailingIcon={<ArrowRightIcon />}
            >
              {ready ? 'Review analysis' : 'Open tender'}
            </ActionButton>
          </div>
        </div>
      </div>
    </Panel>
  )
}

export function TenderProcessingPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [retryToken, setRetryToken] = useState(0)

  /* No dependencies: the queue is the live pipeline, and nothing on this page filters
     it. It is refetched when a watched tender settles (see `onFinished`). */
  const tenders = useAsyncData((signal) => listTenders({ limit: QUEUE_LIMIT }, { signal }), [])
  const rows = useMemo(() => tenders.data ?? [], [tenders.data])

  /* Everything not finalized: the working stages, the failures, and the ones waiting
     on a reviewer. A finalized tender has left the pipeline and lives in Overview. */
  const queueTenders = useMemo(
    () =>
      rows.filter(
        (tender) =>
          isInFlight(tender.status) ||
          tender.status === 'failed' ||
          tender.status === 'ready_for_review',
      ),
    [rows],
  )

  const ordered = useMemo(
    () =>
      [...queueTenders].sort((a, b) => {
        const rank = tenderRank(a) - tenderRank(b)

        if (rank !== 0) {
          return rank
        }

        /* ISO-8601 sorts chronologically as a string, so no Date allocation per compare. */
        return b.created_at.localeCompare(a.created_at)
      }),
    [queueTenders],
  )

  const requested = searchParams.get('tender')
  const focused = ordered.find((tender) => tender.id === requested) ?? ordered[0] ?? null

  const running = queueTenders.filter((tender) => isInFlight(tender.status)).length
  const failed = queueTenders.filter((tender) => tender.status === 'failed').length
  const ready = queueTenders.filter((tender) => tender.status === 'ready_for_review').length

  function focusTender(tender: TenderListItem) {
    /* `replace` so scanning the list does not fill the back button with every tender
       glanced at on the way to the one that mattered. */
    setSearchParams({ tender: tender.id }, { replace: true })
  }

  const queueDescription = (() => {
    if (tenders.data === null) {
      return 'Reading the pipeline.'
    }

    const parts: string[] = []

    if (running > 0) {
      parts.push(`${formatCount(running)} analysing`)
    }
    if (ready > 0) {
      parts.push(`${formatCount(ready)} ready for review`)
    }
    if (failed > 0) {
      parts.push(`${formatCount(failed)} failed`)
    }

    return parts.length > 0 ? parts.join(' · ') : 'Everything here has finished.'
  })()

  /* The whole page is one read, so a failure with nothing to show replaces the layout
     rather than framing an error in an empty two-column shell. */
  if (tenders.status === 'error' && tenders.data === null) {
    return (
      <Panel title="Processing">
        <ErrorBlock
          title="The pipeline could not be read"
          message={tenders.error ?? 'The request did not complete.'}
          offline={tenders.offline}
          onRetry={tenders.refetch}
        />
      </Panel>
    )
  }

  if (tenders.status === 'loading' && tenders.data === null) {
    return (
      <Panel title="Processing" description="Reading the pipeline.">
        <LoadingRows rows={4} label="Loading the tender pipeline" />
      </Panel>
    )
  }

  if (!focused) {
    return (
      <Panel
        title="Processing"
        description="Tenders being analysed appear here while they work."
        action={
          <ActionButton
            variant="secondary"
            size="sm"
            leadingIcon={<RefreshIcon />}
            disabled={tenders.isRefreshing}
            onClick={tenders.refetch}
          >
            Refresh
          </ActionButton>
        }
      >
        <div className="py-10">
          <TableEmptyState
            icon={<ActivityIcon className="size-5" />}
            title="Nothing is being analysed"
            description="Every tender has either finished or been finalized. Upload a tender to start a new analysis, or open a finalized one from the Overview."
            action={
              <ActionButton
                variant="primary"
                size="sm"
                to={ROUTES.tenderUpload}
                leadingIcon={<UploadIcon />}
                className="mt-1"
              >
                Upload a tender
              </ActionButton>
            }
          />
        </div>
      </Panel>
    )
  }

  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
      <div className="min-w-0 flex-1">
        <TenderWatcher
          key={`${focused.id}:${retryToken}`}
          tender={focused}
          onRetry={() => setRetryToken((token) => token + 1)}
          onFinished={tenders.refetch}
        />
      </div>

      <div className="w-full xl:max-w-sm">
        <Panel
          title="Pipeline"
          description={queueDescription}
          action={
            <ActionButton
              variant="secondary"
              size="sm"
              leadingIcon={<RefreshIcon />}
              disabled={tenders.isRefreshing}
              onClick={tenders.refetch}
              hideLabelOnMobile
            >
              Refresh
            </ActionButton>
          }
          flush
        >
          {tenders.status === 'error' ? (
            <StaleDataNotice
              message={tenders.error ?? 'The last refresh did not complete.'}
              onRetry={tenders.refetch}
            />
          ) : null}

          {/*
            Buttons, not links. Each one changes which tender the panel beside it shows —
            a control on this page, not a navigation away from it — and the URL it writes
            is a `replace`. `aria-current` tells a reader which row is the one on screen.
          */}
          <ul className="flex flex-col divide-y divide-hairline">
            {ordered.map((tender) => {
              const isFocused = focused.id === tender.id
              /* A bar while the work is live or where it stopped; none once it is settled
                 successfully — a full bar next to a "Ready for review" chip says the same
                 thing twice, and `ready_for_review`/`finalized` are not a percentage. */
              const showBar = isInFlight(tender.status) || tender.status === 'failed'

              return (
                <li key={tender.id}>
                  <button
                    type="button"
                    onClick={() => focusTender(tender)}
                    aria-current={isFocused ? 'true' : undefined}
                    className={[
                      'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors duration-150',
                      isFocused ? 'bg-brand-50/60' : 'hover:bg-surface-muted',
                    ].join(' ')}
                  >
                    <FileGlyph filename={tender.original_filename} />

                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-neutral-900">
                        {tenderTitle(tender)}
                      </span>

                      <span className="mt-1.5 flex flex-wrap items-center gap-2">
                        <TenderStatusPill status={tender.status} />
                        <span className="text-xs text-neutral-500 tabular-nums">
                          {formatRelativeTime(tender.created_at)}
                        </span>
                      </span>

                      {showBar ? (
                        <span
                          aria-hidden="true"
                          className="mt-2 block h-1 overflow-hidden rounded-full bg-neutral-200"
                        >
                          <span
                            className={[
                              'block h-full rounded-full',
                              tender.status === 'failed' ? 'bg-rose-400' : 'bg-brand-500',
                            ].join(' ')}
                            style={{
                              width: `${Math.min(100, Math.max(0, tender.progress_percent))}%`,
                            }}
                          />
                        </span>
                      ) : null}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>

          {running === 0 ? (
            <p className="flex items-start gap-2 border-t border-hairline px-4 py-3 text-xs leading-relaxed text-neutral-500">
              <CheckCircleIcon className="mt-px size-3.5 shrink-0 text-emerald-600" />
              <span>
                No tender is being analysed right now.{' '}
                <Link
                  to={ROUTES.tenderUpload}
                  className="font-medium text-brand-600 underline-offset-2 hover:underline"
                >
                  Upload a tender
                </Link>{' '}
                to start one.
              </span>
            </p>
          ) : null}
        </Panel>
      </div>
    </div>
  )
}
