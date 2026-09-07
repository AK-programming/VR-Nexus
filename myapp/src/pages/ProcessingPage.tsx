/**
 * What the indexing workers are doing right now.
 *
 * One job is in focus and the rest are a list beside it. The alternative — five
 * timelines stacked — spends the whole screen redrawing the same five nodes and still
 * makes it hard to see which job needs attention. The focused job gets the full track;
 * every other job gets one line with its stage and a progress bar, which is enough to
 * decide whether to look at it.
 *
 * **The queue is derived from the server, not from this tab.** `listProcessingQueue`
 * reads every unfinished document and pairs it with its newest job row. That is the
 * difference between this page and the harness it replaces, whose queue was an array of
 * jobs the current page had started: reload, open a second tab, or come back to a job a
 * colleague queued, and the harness showed an empty list while work was plainly running.
 *
 * **A document with no job is not the same as a queued one.** `queued` is the status a
 * document is *born* with, so an upload that nobody indexed sits at `queued` forever with
 * no job row behind it. Rendering that as "Queued" alongside jobs a worker really is
 * holding would hide the one thing worth knowing — that nothing will ever happen to it
 * until someone presses Index. Those entries get their own treatment and their own
 * button.
 *
 * `?job=` in the URL is what Library and Upload navigate to after starting work, so
 * "index this, then watch it" is one continuous motion rather than a page that lands
 * you at the top of a list to find your own document. It also makes a particular job
 * linkable, which matters when the answer to "why did this fail" is being pasted into
 * a chat. `?doc=` is the same idea for an entry that has no job to point at yet.
 *
 * Connection state is shown rather than hidden. A silent timeline that has stopped
 * updating is indistinguishable from a job that is genuinely stuck, and the difference
 * is the only thing a reader actually needs: `live` is a socket, `polling` is the
 * two-second fallback, `offline` means the service is unreachable and nothing on screen
 * is current. See `useJobProgress` for how the fallback is chosen.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ROUTES, documentViewerPath } from '@/constants/routes'
import { STAGE_LABELS, documentTitle, isTerminalStage } from '@/models/documents'
import type { IndexJob, LibraryDocument } from '@/models/documents'
import { listProcessingQueue, train } from '@/services/documentService'
import type { QueueEntry } from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useJobProgress } from '@/hooks/useJobProgress'
import type { JobConnection } from '@/hooks/useJobProgress'
import { errorMessage } from '@/lib/apiClient'
import { formatCount, formatRelativeTime } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import type { AlertTone } from '@/components/feedback/AlertMessage'
import { ErrorBlock, LoadingRows, StaleDataNotice } from '@/components/feedback/DataState'
import { ProcessingTimeline } from '@/components/documents/ProcessingTimeline'
import { JobStagePill } from '@/components/documents/JobStagePill'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { TableEmptyState } from '@/components/ui/DataTable'
import {
  ActivityIcon,
  ArrowRightIcon,
  CheckCircleIcon,
  DatabaseIcon,
  RefreshIcon,
  SignalOffIcon,
  UploadIcon,
} from '@/components/ui/icons'

type Notice = { tone: AlertTone; text: string } | null

/** How each connection state is worded and painted. */
const CONNECTION_NOTES: Record<JobConnection, { label: string; classes: string }> = {
  idle: { label: 'Connecting', classes: 'border-neutral-200 bg-neutral-100 text-neutral-700' },
  live: { label: 'Live', classes: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  polling: { label: 'Polling every 2s', classes: 'border-sky-200 bg-sky-50 text-sky-800' },
  offline: { label: 'Service unreachable', classes: 'border-amber-200 bg-amber-50 text-amber-900' },
  closed: { label: 'Finished', classes: 'border-neutral-200 bg-neutral-100 text-neutral-700' },
}

/**
 * Where an entry sorts. Lower rises.
 *
 * Work in flight first, because that is what someone opening this page came to watch.
 * Failures next, because they are the only rows that need a decision. Never-started
 * after that — they need a decision too, but a cheaper one. Anything finished sinks;
 * in practice those are rare here, since a completed document leaves the queue read
 * entirely once its status becomes `indexed`.
 */
function entryRank(entry: QueueEntry): number {
  if (entry.job === null) {
    return 2
  }
  if (entry.job.stage === 'failed') {
    return 1
  }
  if (entry.job.stage === 'complete') {
    return 3
  }
  return 0
}

/** The timestamp an entry is sorted and labelled by: the job's if there is one. */
function entryTime(entry: QueueEntry): string {
  return entry.job?.updated_at ?? entry.document.created_at
}

function ConnectionNote({ connection }: { connection: JobConnection }) {
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
 * The chip for a document no worker has ever been asked to touch.
 *
 * Deliberately not `TrainingStatusPill`, which would render this document's real status —
 * `queued` — and so state the opposite of the truth. Nothing is queued about it.
 */
function NotStartedPill() {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap text-amber-900">
      Not started
    </span>
  )
}

/**
 * The focused job's live view.
 *
 * A separate component so the parent can remount it with a `key`, which is what Retry
 * does: the hook's socket-and-poll lifecycle lives in one effect keyed on the job id,
 * so the honest way to start over is to give it a new instance rather than add a
 * `retry()` that has to unpick the same teardown by hand.
 *
 * There is no `initialFailedAt` any more. It used to come from a mock that recorded which
 * stage each fixture died at; the API does not carry that — a failed `IndexJob` reports
 * `stage: 'failed'` and nothing about where it got to. So `useJobProgress` infers it from
 * the last real stage it *observes*, which works for a job that fails while being
 * watched and honestly cannot for one that failed yesterday. The timeline marks the
 * failure on the track without claiming a node it cannot know.
 */
function JobWatcher({
  jobId,
  initialJob,
  document,
  onRetry,
  onFinished,
}: {
  jobId: string
  initialJob: IndexJob
  document: LibraryDocument
  onRetry: () => void
  onFinished: () => void
}) {
  const { job, failedAt, connection } = useJobProgress(jobId, { initialJob })
  const current = job ?? initialJob

  /*
   * Seeded with whether the job was *already* finished when this mounted, so opening a
   * long-failed job does not fire a pointless refetch. Only a transition into a terminal
   * stage counts — that is the moment the document's status changes on the server and
   * the queue beside this panel goes stale.
   *
   * The ref also makes this fire once. Without it, every subsequent frame on a completed
   * job would queue another refetch.
   */
  const settledRef = useRef(isTerminalStage(initialJob.stage))

  useEffect(() => {
    if (settledRef.current || !isTerminalStage(current.stage)) {
      return
    }

    settledRef.current = true
    onFinished()
  }, [current.stage, onFinished])

  return (
    <Panel
      title={documentTitle(document)}
      description={`${STAGE_LABELS[current.stage]} · updated ${formatRelativeTime(current.updated_at)}`}
      action={<ConnectionNote connection={connection} />}
    >
      <div className="flex flex-col gap-5">
        <ProcessingTimeline
          stage={current.stage}
          failedAt={failedAt}
          progress={current.progress}
          message={current.message}
        />

        {/* The failure gets its own block rather than only the marked node: the node
            says where it stopped, this says what to do about it. */}
        {current.stage === 'failed' ? (
          <AlertMessage tone="warning" title="This document was not indexed">
            {current.message ||
              document.training_error ||
              'The worker stopped before the document was searchable. Re-index it from the library, or replace the file if the text cannot be read.'}
          </AlertMessage>
        ) : null}

        {connection === 'offline' ? (
          <AlertMessage tone="neutral" icon={<SignalOffIcon />} title="Progress is not updating">
            The indexing service is not reachable, so what is shown is the last state on
            record. Everything below keeps working - this panel refreshes itself as soon
            as the service answers.
          </AlertMessage>
        ) : null}

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="truncate text-xs text-neutral-500">{document.original_filename}</p>

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
              variant="secondary"
              size="sm"
              to={documentViewerPath(document.id)}
              trailingIcon={<ArrowRightIcon />}
            >
              Open document
            </ActionButton>
          </div>
        </div>
      </div>
    </Panel>
  )
}

/**
 * The focused panel for a document with no job behind it.
 *
 * There is nothing to watch, so this does not pretend to: no timeline, no socket, no
 * progress bar sitting at zero. It states why nothing is happening and offers the one
 * thing that changes that.
 */
function WaitingPanel({
  document,
  busy,
  onIndex,
}: {
  document: LibraryDocument
  busy: boolean
  onIndex: () => void
}) {
  return (
    <Panel
      title={documentTitle(document)}
      description={`Uploaded ${formatRelativeTime(document.created_at)} · never indexed`}
    >
      <div className="flex flex-col gap-5">
        <AlertMessage tone="info" title="This document has not been indexed">
          Uploading stores a file; indexing is what makes it searchable. No worker has been
          asked to parse this one yet, so it will not appear in any answer VR-Nexus writes.
        </AlertMessage>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p className="truncate text-xs text-neutral-500">{document.original_filename}</p>

          <div className="flex flex-wrap gap-2">
            <ActionButton
              variant="primary"
              size="sm"
              leadingIcon={<DatabaseIcon />}
              disabled={busy}
              onClick={onIndex}
            >
              Index now
            </ActionButton>
            <ActionButton
              variant="secondary"
              size="sm"
              to={documentViewerPath(document.id)}
              trailingIcon={<ArrowRightIcon />}
            >
              Open document
            </ActionButton>
          </div>
        </div>
      </div>
    </Panel>
  )
}

export function ProcessingPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [retryToken, setRetryToken] = useState(0)
  const [notice, setNotice] = useState<Notice>(null)
  const [busy, setBusy] = useState(false)

  /*
   * No dependencies: the queue is the whole pipeline, and nothing on this page filters
   * it. It is refetched explicitly — when a watched job finishes, and after Index.
   */
  const queue = useAsyncData((signal) => listProcessingQueue({ signal }), [])
  const entries = useMemo(() => queue.data ?? [], [queue.data])

  const ordered = useMemo(
    () =>
      [...entries].sort((a, b) => {
        const rank = entryRank(a) - entryRank(b)

        if (rank !== 0) {
          return rank
        }

        /* ISO-8601 sorts chronologically as a string, so no Date allocation per compare. */
        return entryTime(b).localeCompare(entryTime(a))
      }),
    [entries],
  )

  /*
   * An unknown `?job=` falls back to the top of the list rather than showing an error: a
   * job id ages out — the document finishes and leaves this read — and a stale link
   * should still land somewhere useful rather than on a dead end.
   */
  const requestedJob = searchParams.get('job')
  const requestedDoc = searchParams.get('doc')

  const focused =
    ordered.find((entry) => entry.job !== null && entry.job.id === requestedJob) ??
    ordered.find((entry) => entry.document.id === requestedDoc) ??
    ordered[0] ??
    null

  const running = entries.filter(
    (entry) => entry.job !== null && !isTerminalStage(entry.job.stage),
  ).length
  const failed = entries.filter((entry) => entry.job?.stage === 'failed').length
  const notStarted = entries.filter((entry) => entry.job === null).length

  function focusEntry(entry: QueueEntry) {
    /* `replace` so selecting through the list does not fill the back button with every
       job that was glanced at on the way to the one that mattered. */
    setSearchParams(
      entry.job !== null ? { job: entry.job.id } : { doc: entry.document.id },
      { replace: true },
    )
  }

  /**
   * Sends documents to the workers.
   *
   * An empty `ids` is not a no-op — `POST /train` with no document ids trains everything
   * currently queued, which is exactly what "Index all waiting" means. The two callers
   * below rely on that.
   */
  async function handleIndex(ids: string[]) {
    setBusy(true)
    setNotice(null)

    try {
      const response = await train(ids)
      const started = response.jobs.length
      const firstJob = response.jobs[0]

      queue.refetch()

      if (firstJob) {
        setSearchParams({ job: firstJob.id }, { replace: true })
      }

      if (started === 0) {
        /* `skipped` is the ordinary answer to indexing something already indexed or
           already held by a worker. It is not a failure and is not painted as one. */
        setNotice({
          tone: 'info',
          text: 'Nothing was queued - those documents are already indexed or already with a worker.',
        })
      } else {
        setNotice({
          tone: 'success',
          text: `${formatCount(started)} ${started === 1 ? 'document' : 'documents'} sent to the workers.`,
        })
      }
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  const queueDescription = (() => {
    if (queue.data === null) {
      return 'Reading the pipeline.'
    }

    const parts: string[] = []

    if (running > 0) {
      parts.push(`${formatCount(running)} running`)
    }
    if (failed > 0) {
      parts.push(`${formatCount(failed)} failed`)
    }
    if (notStarted > 0) {
      parts.push(`${formatCount(notStarted)} not started`)
    }

    return parts.length > 0 ? parts.join(' · ') : 'Everything here has finished.'
  })()

  /* The whole page is one read, so a failure with nothing to show replaces the layout
     rather than rendering an empty two-column shell around an error. */
  if (queue.status === 'error' && queue.data === null) {
    return (
      <Panel title="Processing">
        <ErrorBlock
          title="The processing queue could not be read"
          message={queue.error ?? 'The request did not complete.'}
          offline={queue.offline}
          onRetry={queue.refetch}
        />
      </Panel>
    )
  }

  if (queue.status === 'loading' && queue.data === null) {
    return (
      <Panel title="Processing" description="Reading the pipeline.">
        <LoadingRows rows={4} label="Loading the processing queue" />
      </Panel>
    )
  }

  if (!focused) {
    return (
      <div className="flex flex-col gap-4">
        {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

        <Panel
          title="Processing"
          description="Indexing runs appear here while they are working."
          action={
            <ActionButton
              variant="secondary"
              size="sm"
              leadingIcon={<RefreshIcon />}
              disabled={queue.isRefreshing}
              onClick={queue.refetch}
            >
              Refresh
            </ActionButton>
          }
        >
          <div className="py-10">
            <TableEmptyState
              icon={<ActivityIcon className="size-5" />}
              title="Nothing is being indexed"
              description="Every document in the library is either indexed or has nothing pending. Upload something new, or re-index a document from the library."
              action={
                <ActionButton
                  variant="primary"
                  size="sm"
                  to={ROUTES.documentsUpload}
                  leadingIcon={<UploadIcon />}
                  className="mt-1"
                >
                  Upload documents
                </ActionButton>
              }
            />
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="min-w-0 flex-1">
          {focused.job !== null ? (
            <JobWatcher
              key={`${focused.job.id}:${retryToken}`}
              jobId={focused.job.id}
              initialJob={focused.job}
              document={focused.document}
              onRetry={() => setRetryToken((token) => token + 1)}
              onFinished={queue.refetch}
            />
          ) : (
            <WaitingPanel
              document={focused.document}
              busy={busy}
              onIndex={() => void handleIndex([focused.document.id])}
            />
          )}
        </div>

        <div className="w-full xl:max-w-sm">
          <Panel
            title="Queue"
            description={queueDescription}
            action={
              notStarted > 0 ? (
                <ActionButton
                  variant="secondary"
                  size="sm"
                  leadingIcon={<DatabaseIcon />}
                  disabled={busy}
                  onClick={() => void handleIndex([])}
                  hideLabelOnMobile
                >
                  Index all waiting
                </ActionButton>
              ) : (
                <ActionButton
                  variant="secondary"
                  size="sm"
                  leadingIcon={<RefreshIcon />}
                  disabled={queue.isRefreshing}
                  onClick={queue.refetch}
                  hideLabelOnMobile
                >
                  Refresh
                </ActionButton>
              )
            }
            flush
          >
            {queue.status === 'error' ? (
              <StaleDataNotice
                message={queue.error ?? 'The last refresh did not complete.'}
                onRetry={queue.refetch}
              />
            ) : null}

            {/*
              Buttons, not links. Each one changes which job the panel beside it is
              showing — it is a control on this page, not a navigation to another one,
              and the URL it writes is a `replace`. `aria-current` is what tells a reader
              which of the rows is the one on screen.
            */}
            <ul className="flex flex-col divide-y divide-hairline">
              {ordered.map((entry) => {
                const { document, job } = entry
                const isFocused = focused.document.id === document.id

                return (
                  <li key={document.id}>
                    <button
                      type="button"
                      onClick={() => focusEntry(entry)}
                      aria-current={isFocused ? 'true' : undefined}
                      className={[
                        'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors duration-150',
                        isFocused ? 'bg-selected' : 'hover:bg-surface-muted',
                      ].join(' ')}
                    >
                      <FileGlyph filename={document.original_filename} />

                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-neutral-900">
                          {documentTitle(document)}
                        </span>

                        <span className="mt-1.5 flex flex-wrap items-center gap-2">
                          {job !== null ? <JobStagePill stage={job.stage} /> : <NotStartedPill />}
                          <span className="text-xs text-neutral-500 tabular-nums">
                            {formatRelativeTime(entryTime(entry))}
                          </span>
                        </span>

                        {/* No bar on a finished job: a full green bar and a "Complete"
                            chip say the same thing twice, and the row is calmer without
                            it. A failed job keeps its bar because where it stopped is
                            the information. A job that does not exist gets no bar at
                            all — a track sitting at zero implies work that is not
                            happening. */}
                        {job !== null && job.stage !== 'complete' ? (
                          <span
                            aria-hidden="true"
                            className="mt-2 block h-1 overflow-hidden rounded-full bg-neutral-200"
                          >
                            <span
                              className={[
                                'block h-full rounded-full',
                                job.stage === 'failed' ? 'bg-rose-400' : 'bg-brand-500',
                              ].join(' ')}
                              style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }}
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
                  No worker is busy. Index something from the{' '}
                  <Link
                    to={ROUTES.documents}
                    className="font-medium text-brand-600 underline-offset-2 hover:underline"
                  >
                    library
                  </Link>{' '}
                  to add to this queue.
                </span>
              </p>
            ) : null}
          </Panel>
        </div>
      </div>
    </div>
  )
}
