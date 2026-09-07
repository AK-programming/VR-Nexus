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
 *   no Index button to offer — every tender in this list is already moving or has
 *   finished analysing.
 *
 *   **This page does not mutate.** The library page can start work (train). Here the
 *   only actions are watch, reconnect, and open — finalizing a reviewed tender is a
 *   decision made on the tender's own page, after reading the requirements and
 *   coverage, not a button on a progress screen. So there is no busy state and no
 *   notice: the page reads, and hands off.
 *
 * The queue is every tender that is **still live** — the eight working stages and
 * the ones sitting at `ready_for_review` waiting for a person. A failed tender has
 * nothing left to watch and a finalized one has left the pipeline for good; both
 * live in the Overview list, where a failed run can be retried.
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
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { ROUTES, tenderDetailPath } from '@/constants/routes'
import {
  TENDER_STATUS_LABELS,
  isInFlight,
  isSettled,
  progressFromDetail,
  tenderTitle,
} from '@/models/tenders'
import type { TenderListItem, TenderStatus } from '@/models/tenders'
import {
  cancelTender,
  deleteTender,
  listTenders,
  reportTenderIssue,
} from '@/services/tenderService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useTenderProgress } from '@/hooks/useTenderProgress'
import type { TenderConnection } from '@/hooks/useTenderProgress'
import { formatCount, formatRelativeTime } from '@/lib/formatting'
import { errorMessage } from '@/lib/apiClient'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ErrorBlock, LoadingRows, StaleDataNotice } from '@/components/feedback/DataState'
import { TenderTimeline } from '@/components/tender/TenderTimeline'
import { TenderStatusPill } from '@/components/tender/TenderStatusPill'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { TableEmptyState } from '@/components/ui/DataTable'
import {
  ActivityIcon,
  ArrowRightIcon,
  BanIcon,
  CheckCircleIcon,
  LifeBuoyIcon,
  RefreshIcon,
  SignalOffIcon,
  SpinnerIcon,
  TrashIcon,
  UploadIcon,
  XCircleIcon,
} from '@/components/ui/icons'

/* In-flight tenders are always among the most recent, so a bounded recent window
   holds the whole live queue without a dedicated endpoint. */
const QUEUE_LIMIT = 100

/** How many failures the error log shows at once. See `failures` for why bounded. */
const FAILURE_LOG_LIMIT = 10

/** How recent a failure has to be to show in the error log, in milliseconds.
 *  The log is a "what just broke" surface, not a permanent archive — a failure
 *  from days ago belongs on the tender's own row in the Overview list, where it
 *  can still be retried or deleted. Any failure older than this window falls out
 *  of the log on its own; a Delete on a row inside the window is what removes a
 *  recent one from the log without deleting the tender. */
const FAILURE_LOG_MAX_AGE_MS = 24 * 60 * 60 * 1000

/** Where "Contact technical support" routes a failure. Kept in sync with the
 *  backend's SUPPORT_EMAIL default; used to address the Gmail compose window the
 *  "Contact technical support" button opens. */
const SUPPORT_EMAIL = 'engrak2155@gmail.com'

function supportGmailCompose(tender: TenderListItem): string {
  const subject = `VR-Nexus: tender analysis failed - ${tenderTitle(tender)}`
  const detail = (tender.error_detail ?? '').slice(0, 3000)
  const body = [
    'Hello support team,',
    '',
    'A tender analysis failed in VR-Nexus. The details are below.',
    '',
    `Tender: ${tenderTitle(tender)}`,
    `File: ${tender.original_filename}`,
    `Failed at: ${tender.failed_stage ?? 'unknown stage'}`,
    `Reference: ${tender.id}`,
    '',
    `Reason: ${tender.progress_message ?? 'No reason recorded.'}`,
    '',
    'Technical detail:',
    detail || 'None recorded.',
    '',
    'Thank you.',
  ].join('\n')
  return (
    'https://mail.google.com/mail/?view=cm&fs=1' +
    `&to=${encodeURIComponent(SUPPORT_EMAIL)}` +
    `&su=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`
  )
}

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
 * Tenders ready for review last: a decision too, but a welcome one that can wait.
 * Failed and finalized tenders are filtered out before this runs.
 */
function tenderRank(tender: TenderListItem): number {
  return isInFlight(tender.status) ? 0 : 1
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

  const [stopping, setStopping] = useState(false)

  async function handleStop() {
    setStopping(true)
    try {
      await cancelTender(tender.id)
      onFinished()
    } catch {
      /* the socket will still show the real state; nothing to surface here */
    } finally {
      setStopping(false)
    }
  }

  return (
    <Panel
      collapsible
      defaultOpen
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
              'The pipeline stopped before the analysis finished.'}{' '}
            It has left the queue. You can retry it from the Tender Overview list once
            you have checked that the source PDF is readable.
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
            {isInFlight(current.status) ? (
              <ActionButton
                variant="danger"
                size="sm"
                leadingIcon={<BanIcon />}
                disabled={stopping}
                onClick={handleStop}
              >
                {stopping ? 'Stopping…' : 'Stop'}
              </ActionButton>
            ) : null}
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

/* -------------------------------------------------------------------------- */
/* Error log                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Why a run stopped.
 *
 * Failed tenders leave the queue above (there is no progress left to watch), and
 * this is where they come to rest — so that "it did not finish" is never the
 * whole story the page tells. Each entry answers three questions in the order
 * they get asked: **where** it died (the stage, from `failed_stage`), **what**
 * happened (`progress_message`, the one-line reason), and, for whoever has to
 * fix it, the exception and the tail of its stack behind a disclosure.
 *
 * The stack is collapsed rather than absent. A stack trace on screen by default
 * turns an operator's page into a developer's, but not having it at all is what
 * forces someone into the worker's container logs to answer "which call failed" —
 * the one question the log exists for.
 *
 * Retry lives here as well as on Overview: having read why a run failed and fixed
 * it, the next thing wanted is to run it again, and sending the reader to another
 * screen to press the same button is a step with no decision in it.
 *
 * Rows come from the list read the page already makes — no request per failure.
 */
function TenderErrorLog({
  failures,
  onRetried,
}: {
  failures: TenderListItem[]
  /* Fires after any list-mutating action (retry, delete) so the parent refetches
     and this component gets a fresh `failures` prop — retried rows leave for the
     queue above, deleted rows disappear from the list entirely. */
  onRetried: () => void
}) {
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [reportingId, setReportingId] = useState<string | null>(null)
  /* The row the delete-confirm dialog is asking about. `null` closes it. */
  const [pendingDelete, setPendingDelete] = useState<TenderListItem | null>(null)
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  /**
   * Deletes a failed tender. The parent refetches, which drops the row from
   * `failures` and this entry disappears from the log — which is what the user
   * asked for when they wanted the log to stop carrying an old failure they no
   * longer care about (a Reanalyse's alternative, not the same thing).
   */
  async function performDelete(tender: TenderListItem) {
    setDeletingId(tender.id)
    setNotice(null)

    try {
      await deleteTender(tender.id)
      setNotice({
        tone: 'success',
        text: `"${tenderTitle(tender)}" was deleted and removed from the log.`,
      })
      onRetried()
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setDeletingId(null)
      setPendingDelete(null)
    }
  }

  /**
   * Hands a failed tender to the support team. Opens the user's Gmail with a new
   * message already addressed to support and filled with the failure, so they
   * only press Send. The window is opened synchronously inside the click so a
   * popup blocker treats it as user-initiated; the backend call that records the
   * hand-off (so the "please wait" state survives a reload) runs after.
   */
  function reportIssue(tender: TenderListItem) {
    // Open the compose window first, in the click's own gesture.
    window.open(supportGmailCompose(tender), '_blank', 'noopener,noreferrer')
    void markReported(tender)
  }

  async function markReported(tender: TenderListItem) {
    setReportingId(tender.id)
    setNotice(null)

    try {
      await reportTenderIssue(tender.id)
      setNotice({
        tone: 'success',
        text: 'Your email to the support team is open. Once you press Send in Gmail, we will take it from there.',
      })
      onRetried()
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setReportingId(null)
    }
  }

  return (
    <Panel
      collapsible
      /* Open when there is something to read, closed when the log is empty: a
         panel whose only content is "nothing here" should not be occupying the
         screen of someone watching a run that is going fine. */
      defaultOpen={failures.length > 0}
      title="Error log"
      description={
        failures.length === 0
          ? 'Nothing has failed in the last 24 hours.'
          : `${formatCount(failures.length)} ${
              failures.length === 1 ? 'run' : 'runs'
            } stopped in the last 24 hours.`
      }
      flush
    >
      {notice ? (
        <div className="px-4 pt-4">
          <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage>
        </div>
      ) : null}

      {failures.length === 0 ? (
        <p className="flex items-start gap-2 px-4 py-4 text-xs leading-relaxed text-neutral-500">
          <CheckCircleIcon className="mt-px size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
          <span>
            Nothing has failed in the last 24 hours. Older failures live on their
            tender's row in{' '}
            <Link
              to={ROUTES.tenderAnalysis}
              className="font-medium text-brand-600 underline-offset-2 hover:underline"
            >
              Tender Overview
            </Link>
            .
          </span>
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-hairline">
          {failures.map((tender) => {
            const isReporting = reportingId === tender.id
            const isBusy = isReporting || deletingId === tender.id
            const reported = tender.support_requested_at !== null
            /* `failed_stage` is a raw status string from the server. Map it through
               the label table when it is one this client knows, and show it as-is
               when it is not — an unrecognised stage name is still more useful than
               dropping the only clue about where the run died. */
            const stageLabel = tender.failed_stage
              ? (TENDER_STATUS_LABELS[tender.failed_stage as TenderStatus] ??
                tender.failed_stage)
              : null
            const when = tender.failed_at ?? tender.created_at

            return (
              <li key={tender.id} className="px-4 py-3">
                <div className="flex items-start gap-3">
                  <XCircleIcon className="mt-0.5 size-4 shrink-0 text-rose-500" />

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Link
                        to={tenderDetailPath(tender.id)}
                        className="truncate text-sm font-medium text-neutral-900 underline-offset-2 hover:text-brand-700 hover:underline"
                      >
                        {tenderTitle(tender)}
                      </Link>

                      {stageLabel ? (
                        <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-medium text-rose-700">
                          Could not finish {stageLabel}
                        </span>
                      ) : null}

                      <span className="text-xs text-neutral-500 tabular-nums">
                        {formatRelativeTime(when)}
                      </span>
                    </div>

                    {reported ? (
                      /* Reported state. The technical reason and the Retry button
                         are gone — a non-technical user has handed this to the
                         people who can fix it, and the only thing they need now is
                         reassurance. The raw error still travels to support by
                         email; it is not shown here. */
                      <div className="mt-2 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 px-3 py-2.5">
                        <CheckCircleIcon className="mt-px size-4 shrink-0 text-emerald-600" />
                        <p className="text-sm leading-relaxed text-emerald-900">
                          This has been sent to our technical support team. Please
                          wait while they look into it. It is usually fixed within 3
                          to 4 working days. Thank you for your patience.
                        </p>
                      </div>
                    ) : (
                      <p className="mt-1 text-sm leading-relaxed text-neutral-700">
                        This tender could not be analysed. Our technical team can look
                        into why and put it right. Send it to them with the button on
                        the right, then press Send in the Gmail window that opens.
                      </p>
                    )}
                  </div>

                  {reported ? (
                    /* Only Delete remains once reported — "remove this from my list".
                       Retry is intentionally gone: support is handling it, and a
                       user re-running it themselves would only reproduce the failure. */
                    <ActionButton
                      variant="secondary"
                      size="sm"
                      disabled={deletingId === tender.id}
                      leadingIcon={
                        deletingId === tender.id ? (
                          <SpinnerIcon className="size-4 animate-spin" />
                        ) : (
                          <TrashIcon className="size-4" />
                        )
                      }
                      onClick={() => setPendingDelete(tender)}
                      hideLabelOnMobile
                    >
                      {deletingId === tender.id ? 'Removing' : 'Remove'}
                    </ActionButton>
                  ) : (
                    <div className="flex flex-nowrap items-start gap-1.5">
                      <ActionButton
                        variant="primary"
                        size="sm"
                        disabled={isBusy}
                        leadingIcon={
                          isReporting ? (
                            <SpinnerIcon className="size-4 animate-spin" />
                          ) : (
                            <LifeBuoyIcon className="size-4" />
                          )
                        }
                        onClick={() => {
                          reportIssue(tender)
                        }}
                        hideLabelOnMobile
                      >
                        {isReporting ? 'Sending' : 'Contact technical support'}
                      </ActionButton>

                      <ActionButton
                        variant="danger"
                        size="sm"
                        disabled={isBusy}
                        leadingIcon={
                          deletingId === tender.id ? (
                            <SpinnerIcon className="size-4 animate-spin" />
                          ) : (
                            <TrashIcon className="size-4" />
                          )
                        }
                        onClick={() => setPendingDelete(tender)}
                        hideLabelOnMobile
                      >
                        {deletingId === tender.id ? 'Deleting' : 'Delete'}
                      </ActionButton>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {/* Confirm dialog at the panel root, not inside the row: the row unmounts as
          the failures list refetches, which would tear down a dialog mid-answer. */}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this tender?"
        description={
          pendingDelete
            ? `"${tenderTitle(pendingDelete)}" and its output will be removed. This cannot be undone.`
            : ''
        }
        confirmLabel={deletingId !== null ? 'Deleting…' : 'Delete tender'}
        onConfirm={() => {
          if (pendingDelete) void performDelete(pendingDelete)
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </Panel>
  )
}


export function TenderProcessingPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [retryToken, setRetryToken] = useState(0)

  /*
   * Upload sends the user straight here, and hands over anything it could not finish
   * on the way (today: tender details that failed to save while the analysis was
   * already running). Read once into state so it survives the `setSearchParams`
   * re-render below and can be dismissed; `location.state` itself would otherwise
   * keep re-appearing on every navigation within the page.
   */
  const location = useLocation()
  const handoff =
    typeof (location.state as { notice?: unknown } | null)?.notice === 'string'
      ? ((location.state as { notice: string }).notice)
      : null
  const [handoffNotice, setHandoffNotice] = useState<string | null>(handoff)

  /* No dependencies: the queue is the live pipeline, and nothing on this page filters
     it. It is refetched when a watched tender settles (see `onFinished`). */
  const tenders = useAsyncData((signal) => listTenders({ limit: QUEUE_LIMIT }, { signal }), [])
  const rows = useMemo(() => tenders.data ?? [], [tenders.data])

  /* Live work only: the eight working stages plus the ones waiting on a reviewer.
     A failed run has nothing left to watch, so it leaves this queue and is retried
     from Overview; a finalized tender has left the pipeline for the same reason. */
  const queueTenders = useMemo(
    () =>
      rows.filter(
        (tender) => isInFlight(tender.status) || tender.status === 'ready_for_review',
      ),
    [rows],
  )

  /* The failures the log below shows. Newest first, and bounded: an error log is
     read to answer "what just broke", not as an archive — the full history of a
     tender lives on its own page. Drawn from the same unfiltered read as the
     queue, so no extra request. */
  const failures = useMemo(() => {
    const now = Date.now()
    return rows
      .filter((tender) => {
        if (tender.status !== 'failed') {
          return false
        }
        /* Age from failed_at (which /cancel and /fail both set); fall back to
           created_at for legacy rows whose failure record was never populated.
           A parse failure (NaN) means we cannot judge the age — show it rather
           than silently hiding what might be the failure the user is here for. */
        const when = Date.parse(tender.failed_at ?? tender.created_at)
        return Number.isNaN(when) || now - when <= FAILURE_LOG_MAX_AGE_MS
      })
      .sort((a, b) =>
        (b.failed_at ?? b.created_at).localeCompare(a.failed_at ?? a.created_at),
      )
      .slice(0, FAILURE_LOG_LIMIT)
  }, [rows])

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
      <div className="flex flex-col gap-4">
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
              description={
                failures.length > 0
                  ? 'Nothing is running right now. The runs that stopped are listed below, with the reason each one gave.'
                  : 'Every tender has either finished or been finalized. Upload a tender to start a new analysis, or open a finalized one from the Overview.'
              }
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

        {/* An empty queue is exactly when the log matters most: with no run to
            watch, "why did nothing finish?" is the only question on the page. */}
        <TenderErrorLog failures={failures} onRetried={tenders.refetch} />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {handoffNotice ? (
        <AlertMessage tone="warning" title="The analysis started, with one thing unsaved">
          {handoffNotice}{' '}
          <button
            type="button"
            className="font-medium underline underline-offset-2"
            onClick={() => setHandoffNotice(null)}
          >
            Dismiss
          </button>
        </AlertMessage>
      ) : null}

      <div className="min-w-0">
        <TenderWatcher
          key={`${focused.id}:${retryToken}`}
          tender={focused}
          onRetry={() => setRetryToken((token) => token + 1)}
          onFinished={tenders.refetch}
        />
      </div>

      <div className="w-full">
        <Panel
          collapsible
          defaultOpen
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
                      isFocused ? 'bg-selected' : 'hover:bg-surface-muted',
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
              <CheckCircleIcon className="mt-px size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
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

      <div className="w-full">
        <TenderErrorLog failures={failures} onRetried={tenders.refetch} />
      </div>
    </div>
  )
}
