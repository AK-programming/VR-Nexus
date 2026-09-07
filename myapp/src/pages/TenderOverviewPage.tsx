/**
 * The Tender Analysis listing — the module's front door.
 *
 * The sibling of `DocumentsOverviewPage`, and it does the same three things a
 * listing does: you find a tender, you see how far through analysis it is, or you
 * add a new one. Opening a tender for review is the detail workspace's job and
 * adding one is Upload's, so neither is duplicated here — the row title links to
 * the first and the header button to the second. There is deliberately **no**
 * delete affordance: the tender API exposes no `DELETE /{id}`, so offering one
 * would be a button that 404s.
 *
 * **Retry lives here, not on the Processing page.** A run that failed has nothing
 * left to watch, so it drops out of the Processing queue entirely and comes to
 * rest in this list — which makes this the only place it can be picked back up.
 * The Retry action posts to `POST /tenders/{id}/reprocess`, which resets the row
 * to `uploaded` and re-enqueues the pipeline; every stage clears its own previous
 * rows, so a retry replaces the failed attempt rather than stacking on it. Only
 * failed rows get the action — a running tender would 409, and a finished one has
 * no reason to be re-read from a listing.
 *
 * **Where the numbers come from — and why the filter is different from Documents.**
 * The library page reads its four figures from a separate `GET /stats` call, so a
 * category/status filter can narrow the *table* on the server while the strip
 * keeps describing the whole library. There is no equivalent tender stats
 * endpoint, so the strip here is reduced from the rows themselves. That single
 * fact drives the whole design of this page: if the status filter were applied on
 * the server, the fetched rows would be only the filtered subset and the strip
 * would silently describe *that*, not the section — exactly the bug the library
 * page's own comments call out. So both filters (status *and* search) run on the
 * client over one unfiltered read, and the strip is always reduced from the full
 * fetch. `WINDOW_ADVISORY` below says out loud when that read hit its ceiling, so
 * the counts never quietly describe a window and call it the section.
 *
 * A firm runs orders of magnitude fewer tenders than it holds library documents,
 * so one 200-row read covering the whole section is the realistic case, not an
 * optimistic one — but the advisory is there for the day it isn't.
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ROUTES, tenderDetailPath } from '@/constants/routes'
import {
  TENDER_STATUSES,
  TENDER_STATUS_LABELS,
  isInFlight,
  tenderTitle,
} from '@/models/tenders'
import type { TenderListItem, TenderStatus } from '@/models/tenders'
import { deleteTender, listTenders, reprocessTender } from '@/services/tenderService'
import { formatCount, formatShortDate } from '@/lib/formatting'
import { useAsyncData } from '@/hooks/useAsyncData'
import { errorMessage } from '@/lib/apiClient'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { Panel } from '@/components/dashboard/Panel'
import { DataTable, TableEmptyState } from '@/components/ui/DataTable'
import type { Column } from '@/components/ui/DataTable'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import {
  AsyncSection,
  ErrorBlock,
  LoadingRows,
  StaleDataNotice,
} from '@/components/feedback/DataState'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { TenderStatusPill } from '@/components/tender/TenderStatusPill'
import {
  ArrowRightIcon,
  CheckCircleIcon,
  ClockIcon,
  FileTextIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
  TrashIcon,
  UploadIcon,
  XCircleIcon,
} from '@/components/ui/icons'

/** `all` is a filter value, not a status, so the two unions are kept separate. */
type StatusFilter = TenderStatus | 'all'

/**
 * How many rows one read pulls.
 *
 * The server bounds `limit` to 1–500 (default 100). 200 is a window, not a
 * guarantee: `GET /tenders` returns a bare array with no total and no cursor, so
 * a client that asked for 200 and got 200 can only honestly say there may be
 * more. Unlike the library, the filters here do not enlarge or move that window —
 * they run in the browser — so a full window is the one case this page cannot
 * fully answer, and it says so rather than pretending otherwise.
 */
const PAGE_SIZE = 200

/** Shared field paint, so the search box and the select are visibly one control set. */
const CONTROL_CLASSES = [
  'h-10 w-full rounded-xl border border-hairline bg-field text-sm text-neutral-900',
  'transition-colors duration-150 hover:border-neutral-300',
  /* Matches TextField's focus treatment rather than the global outline, so a form
     control looks like a form control wherever it appears in this product. */
  'focus:border-brand-400 focus:bg-surface focus:ring-4 focus:ring-brand-500/15 focus:outline-none',
]

/**
 * Everything the search box matches on.
 *
 * The tender list row carries far less than a library document does — no client,
 * sector or keywords — so the haystack is the three text fields it *does* have:
 * the name (which defaults to the filename but is often edited to the tender's
 * real title), the original filename (people remember a document either way), and
 * the issuing authority ("show me the ministry's tenders" is a question this list
 * exists to answer). `issuing_authority` is nullable on the wire, so it is
 * coalesced rather than assumed present.
 */
function searchHaystack(tender: TenderListItem): string {
  return [tender.name, tender.original_filename, tender.issuing_authority ?? '']
    .join(' ')
    .toLowerCase()
}

export function TenderOverviewPage() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  /* Per-row busy ids, so only the tender being acted on spins — a list-wide flag
     would disable every other button for a request that has nothing to do with them. */
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  /* The tender the delete-confirm dialog is asking about. `null` closes the dialog.
     Held as the full row so the confirm sentence can name the file, not just an id. */
  const [pendingDelete, setPendingDelete] = useState<TenderListItem | null>(null)
  const [notice, setNotice] = useState<{ tone: 'success' | 'error'; text: string } | null>(null)

  /*
   * One read, no dependencies. Both filters run on the client (see the file
   * header), so changing them never re-reads — which also means the status filter
   * is instant and never drops the table to a skeleton mid-typing. The strip below
   * is reduced from this same unfiltered set, so it always describes the section
   * rather than the current filter.
   */
  const tenders = useAsyncData(
    (signal) => listTenders({ limit: PAGE_SIZE }, { signal }),
    [],
  )

  const rows = useMemo(() => tenders.data ?? [], [tenders.data])

  const filtersActive = query.trim() !== '' || status !== 'all'

  /* Status and search both applied here, over the full fetch. */
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()

    return rows.filter((tender) => {
      if (status !== 'all' && tender.status !== status) {
        return false
      }
      if (needle !== '' && !searchHaystack(tender).includes(needle)) {
        return false
      }
      return true
    })
  }, [rows, status, query])

  /**
   * The strip's four numbers, reduced from the full fetch in one pass. `null`
   * until the first read lands, so the tiles render a skeleton rather than a
   * momentary zero — "not known yet" and "none" are different answers, and the
   * strip exists to tell them apart.
   *
   * `uploaded` is counted as "waiting" (queued for a worker) and the seven working
   * stages as "running", mirroring the library's queued/processing split; both
   * fold into the in-flight total. `finalized` lands in the total only — it has no
   * tile, because a filed-away tender is not something the operator scans for. It
   * is still reachable through the status select.
   */
  const counts = useMemo(() => {
    if (!tenders.data) {
      return null
    }

    let queued = 0
    let running = 0
    let readyForReview = 0
    let failed = 0

    for (const tender of tenders.data) {
      if (tender.status === 'ready_for_review') {
        readyForReview += 1
      } else if (tender.status === 'failed') {
        failed += 1
      } else if (tender.status === 'uploaded') {
        queued += 1
      } else if (isInFlight(tender.status)) {
        running += 1
      }
    }

    return {
      total: tenders.data.length,
      queued,
      running,
      inFlight: queued + running,
      readyForReview,
      failed,
    }
  }, [tenders.data])

  /** The window is full, so there may be older tenders this page has not loaded. */
  const windowFull = rows.length >= PAGE_SIZE

  /** Toggles a strip tile into and out of the status filter. */
  function selectStatus(next: TenderStatus) {
    setStatus((current) => (current === next ? 'all' : next))
    /* The tile promises "these tenders". A search left in the box would narrow
       that further and make the count disagree with the tile that was clicked. */
    setQuery('')
  }

  function clearFilters() {
    setQuery('')
    setStatus('all')
  }

  /**
   * Re-runs the pipeline for a settled tender and refetches the list so the row
   * moves to `uploaded` on screen. The refetch is what changes the status pill;
   * the response is not written into the table directly, because the list read is
   * the single source of truth for these rows and two writers would drift. Same
   * endpoint (`/reprocess`) for both the failure "Retry" and the finished-run
   * "Reanalyse" — the backend is idempotent about the previous attempt's rows.
   */
  async function retryTender(tender: TenderListItem) {
    setRetryingId(tender.id)
    setNotice(null)

    try {
      await reprocessTender(tender.id)
      setNotice({
        tone: 'success',
        text: `"${tenderTitle(tender)}" was queued for analysis again. Follow it on the Processing page.`,
      })
      tenders.refetch()
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setRetryingId(null)
    }
  }

  /**
   * Deletes a tender and everything it points at — DB rows, source PDF, output
   * folder and zip. Refetches the list so the row disappears; also drops the
   * failure record it may have carried into the Processing page's error log,
   * which reads from the same list. Best-effort file cleanup is on the server
   * side — the API returns 204 on success.
   */
  async function performDelete(tender: TenderListItem) {
    setDeletingId(tender.id)
    setNotice(null)

    try {
      await deleteTender(tender.id)
      setNotice({
        tone: 'success',
        text: `"${tenderTitle(tender)}" and its output were deleted.`,
      })
      tenders.refetch()
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setDeletingId(null)
      setPendingDelete(null)
    }
  }

  const columns: Column<TenderListItem>[] = [
    {
      id: 'tender',
      header: 'Tender',
      sortValue: (tender) => tenderTitle(tender),
      cell: (tender) => (
        <div className="flex min-w-0 items-center gap-3">
          <FileGlyph filename={tender.original_filename} />
          <div className="min-w-0">
            <Link
              to={tenderDetailPath(tender.id)}
              className="block truncate font-medium text-neutral-900 hover:text-brand-700"
            >
              {tenderTitle(tender)}
            </Link>
            <p className="truncate text-xs text-neutral-500">{tender.original_filename}</p>
          </div>
        </div>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      /* Sorted by pipeline position, not alphabetically: the words are not the
         order of the work. */
      sortValue: (tender) => TENDER_STATUSES.indexOf(tender.status),
      cell: (tender) => <TenderStatusPill status={tender.status} />,
    },
    {
      id: 'uploaded',
      header: 'Uploaded',
      className: 'hidden sm:table-cell',
      /* ISO-8601 sorts chronologically as a string, so no Date parsing per compare. */
      sortValue: (tender) => tender.created_at,
      cell: (tender) => (
        <time dateTime={tender.created_at} className="whitespace-nowrap">
          {formatShortDate(tender.created_at)}
        </time>
      ),
    },
    {
      id: 'requirements',
      header: 'Requirements',
      className: 'hidden md:table-cell',
      numeric: true,
      /* A tender with zero extracted requirements has not been read yet (or found
         none), which the dash states more honestly than a 0 that looks like a
         count. */
      sortValue: (tender) => tender.extracted_requirements_count,
      cell: (tender) =>
        tender.extracted_requirements_count > 0 ? (
          formatCount(tender.extracted_requirements_count)
        ) : (
          <span className="text-neutral-400">-</span>
        ),
    },
    {
      id: 'deadline',
      header: 'Deadline',
      className: 'hidden lg:table-cell',
      /* Nulls sort last under the table's ascending order, which is where "no
         known deadline" belongs when someone sorts to find the nearest one. */
      sortValue: (tender) => tender.submission_deadline,
      cell: (tender) =>
        tender.submission_deadline ? (
          <time dateTime={tender.submission_deadline} className="whitespace-nowrap">
            {formatShortDate(tender.submission_deadline)}
          </time>
        ) : (
          <span className="text-neutral-400">-</span>
        ),
    },
    {
      id: 'authority',
      header: 'Issuing authority',
      className: 'hidden xl:table-cell',
      sortValue: (tender) => tender.issuing_authority,
      cell: (tender) =>
        tender.issuing_authority ? (
          <span className="block max-w-[16rem] truncate">{tender.issuing_authority}</span>
        ) : (
          <span className="text-neutral-400">-</span>
        ),
    },
    {
      id: 'actions',
      header: 'Actions',
      className: 'w-px',
      /*
       * Two controls, decided per row:
       *
       * - **Reanalyse** for any *settled* tender (failed, ready-for-review, or
       *   finalized) — the pipeline is idempotent, so re-running is the same
       *   button whether the previous run failed ("Retry") or finished but the
       *   reviewer wants it read again with different evidence in the library
       *   ("Reanalyse"). Not offered while a run is in flight, because the
       *   backend refuses that with a 409 — stopping it first is what the
       *   Processing page's Stop button is for.
       * - **Delete** for every row, at any status. A stuck run is the case a
       *   Delete button exists for, so the button gates on nothing and pops a
       *   confirm dialog to catch a slip. The trash icon is destructive-toned;
       *   the label collapses at narrow widths but the accessible name stays.
       *
       * `flex-nowrap` so a narrow column keeps the two buttons on one line rather
       * than stacking them and forcing the row taller. */
      cell: (tender) => {
        const isRetrying = retryingId === tender.id
        const isDeleting = deletingId === tender.id
        const canReanalyse = !isInFlight(tender.status)
        const reanalyseLabel = tender.status === 'failed' ? 'Retry' : 'Reanalyse'

        return (
          <div className="flex flex-nowrap items-center justify-end gap-1.5">
            {canReanalyse ? (
              <ActionButton
                variant="secondary"
                size="sm"
                disabled={isRetrying || isDeleting}
                leadingIcon={
                  isRetrying ? (
                    <SpinnerIcon className="size-4 animate-spin" />
                  ) : (
                    <RefreshIcon className="size-4" />
                  )
                }
                onClick={() => {
                  void retryTender(tender)
                }}
                hideLabelOnMobile
              >
                {isRetrying ? 'Working' : reanalyseLabel}
              </ActionButton>
            ) : null}

            <ActionButton
              variant="danger"
              size="sm"
              disabled={isRetrying || isDeleting}
              leadingIcon={
                isDeleting ? (
                  <SpinnerIcon className="size-4 animate-spin" />
                ) : (
                  <TrashIcon className="size-4" />
                )
              }
              onClick={() => setPendingDelete(tender)}
              hideLabelOnMobile
            >
              {isDeleting ? 'Deleting' : 'Delete'}
            </ActionButton>
          </div>
        )
      },
    },
  ]

  /** "12 of 40 tenders" while filtering, the plain loaded total otherwise. */
  const panelDescription = (() => {
    if (counts === null) {
      return `${formatCount(visible.length)} ${visible.length === 1 ? 'tender' : 'tenders'}`
    }
    if (filtersActive) {
      return `${formatCount(visible.length)} of ${formatCount(counts.total)} tenders`
    }
    return `${formatCount(counts.total)} ${counts.total === 1 ? 'tender' : 'tenders'}`
  })()

  return (
    <div className="flex flex-col gap-4">
      {/*
        One box, four figures, the same combined shape the dashboard's Quick
        Actions bar and the library strip use. Hidden only on a hard error with
        nothing to show — the panel below then carries the message and the retry.
        On a stale refresh the last-known rows are still in hand, so the strip
        keeps describing them rather than blanking.
      */}
      {tenders.status === 'error' && tenders.data === null ? null : (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-hairline bg-hairline shadow-sm sm:grid-cols-4">
          <SummaryFigure
            icon={<FileTextIcon className="size-4.5" />}
            label="Tenders"
            value={counts?.total ?? null}
          />
          <SummaryFigure
            icon={<ClockIcon className="size-4.5" />}
            label="In progress"
            value={counts?.inFlight ?? null}
            tone="sky"
            /*
              The one tile that leaves the page, because watching a run is what the
              Processing screen is for. Its hint keeps "waiting for a worker" and
              "a worker is on it" apart — a stalled queue and active work have
              different causes, and one merged number hides the difference.
            */
            hint={
              counts && counts.inFlight > 0
                ? `${formatCount(counts.running)} running · ${formatCount(counts.queued)} waiting`
                : undefined
            }
            to={counts && counts.inFlight > 0 ? ROUTES.tenderProcessing : undefined}
            actionLabel="Watch tenders currently being analysed"
          />
          <SummaryFigure
            icon={<CheckCircleIcon className="size-4.5" />}
            label="Ready for review"
            value={counts?.readyForReview ?? null}
            tone="amber"
            onSelect={
              counts && counts.readyForReview > 0
                ? () => selectStatus('ready_for_review')
                : undefined
            }
            active={status === 'ready_for_review'}
            actionLabel="Show only tenders ready for review"
          />
          <SummaryFigure
            icon={<XCircleIcon className="size-4.5" />}
            label="Failed"
            value={counts?.failed ?? null}
            tone="rose"
            onSelect={counts && counts.failed > 0 ? () => selectStatus('failed') : undefined}
            active={status === 'failed'}
            actionLabel="Show only tenders that failed to analyse"
          />
        </div>
      )}

      <Panel
        title="Tenders"
        description={panelDescription}
        action={
          <div className="flex shrink-0 items-center gap-2">
            <IconAction
              label="Refresh the tender list"
              icon={tenders.isRefreshing ? <SpinnerIcon className="animate-spin" /> : <RefreshIcon />}
              disabled={tenders.isRefreshing}
              onClick={tenders.refetch}
            />
            <ActionButton to={ROUTES.tenderUpload} variant="primary" leadingIcon={<UploadIcon />}>
              Upload
            </ActionButton>
          </div>
        }
        flush
      >
        {/* The filter bar sits inside the flush body with its own padding, so the
            table below can run to the card's edges while the controls stay inset. */}
        <div className="flex flex-col gap-3 border-b border-hairline px-5 py-4 lg:flex-row lg:items-center">
          <div className="relative min-w-0 flex-1">
            <label htmlFor="tender-search" className="sr-only">
              Search tenders
            </label>
            <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-neutral-400" />
            <input
              id="tender-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name, filename or authority"
              className={[...CONTROL_CLASSES, 'pr-3.5 pl-10 placeholder:text-neutral-400'].join(' ')}
            />
          </div>

          <div className="flex flex-col gap-3 sm:flex-row lg:shrink-0">
            <div className="sm:w-48">
              <label htmlFor="tender-status" className="sr-only">
                Filter by status
              </label>
              <select
                id="tender-status"
                value={status}
                onChange={(event) => setStatus(event.target.value as StatusFilter)}
                className={[...CONTROL_CLASSES, 'px-3'].join(' ')}
              >
                <option value="all">Any status</option>
                {TENDER_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {TENDER_STATUS_LABELS[value]}
                  </option>
                ))}
              </select>
            </div>

            {/* Only rendered when there is something to clear, so the bar never
                carries a permanently dead button. */}
            {filtersActive ? (
              <ActionButton variant="secondary" onClick={clearFilters}>
                Clear
              </ActionButton>
            ) : null}
          </div>
        </div>

        {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

        {/* A refresh that failed over rows still on screen. They were true a moment
            ago, so they stay; only the claim of freshness goes. */}
        {tenders.status === 'error' && tenders.data !== null ? (
          <StaleDataNotice
            message={tenders.error ?? 'The last refresh did not complete.'}
            onRetry={tenders.refetch}
          />
        ) : null}

        <AsyncSection
          status={tenders.status}
          /* `data !== null`, not `length > 0`: an empty array is a successful read
             of an empty section and belongs in the empty state, not a skeleton. */
          hasData={tenders.data !== null}
          loading={<LoadingRows rows={6} label="Loading tenders" />}
          error={
            <ErrorBlock
              title="The tenders could not be loaded"
              message={tenders.error ?? 'The request did not complete.'}
              offline={tenders.offline}
              onRetry={tenders.refetch}
            />
          }
        >
          <DataTable
            rows={visible}
            columns={columns}
            rowKey={(tender) => tender.id}
            caption="Tenders under analysis"
            initialSort={{ columnId: 'uploaded', direction: 'desc' }}
            rowClassName={(tender) => (tender.status === 'failed' ? 'bg-rose-50/40' : '')}
            empty={
              filtersActive ? (
                <TableEmptyState
                  icon={<SearchIcon className="size-5" />}
                  title="No tenders match"
                  description="Nothing here fits that combination of search and status."
                  action={
                    <ActionButton variant="secondary" size="sm" onClick={clearFilters}>
                      Clear filters
                    </ActionButton>
                  }
                />
              ) : (
                <TableEmptyState
                  icon={<FileTextIcon className="size-5" />}
                  title="No tenders yet"
                  description="Upload a tender document and VR-Nexus will read it clause by clause - extracting requirements, matching your evidence, and scoring coverage."
                  action={
                    <ActionButton
                      to={ROUTES.tenderUpload}
                      variant="primary"
                      size="sm"
                      leadingIcon={<UploadIcon />}
                    >
                      Upload a tender
                    </ActionButton>
                  }
                />
              )
            }
          />

          {/*
            Where the window ends, stated rather than implied. `GET /tenders`
            returns a bare array with no total, and — unlike the library — the
            filters on this page run in the browser, so they cannot reach a tender
            that was never loaded. The honest instruction is therefore the opposite
            of the library's: not "filter to reach the rest" but "the rest is not
            here". In practice a section rarely holds this many.
          */}
          {windowFull ? (
            <p className="border-t border-hairline bg-surface-muted px-5 py-3 text-xs text-neutral-500">
              Showing the {formatCount(PAGE_SIZE)} most recent tenders. Older tenders are not
              loaded on this page.
            </p>
          ) : null}
        </AsyncSection>
      </Panel>

      {/* The confirm dialog for Delete lives at the page root, not inside the
          Actions cell — the cell unmounts as the row re-sorts or the table filters,
          which would tear down the dialog mid-answer. Rendered from `pendingDelete`
          rather than a boolean so the sentence names the file being deleted. */}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete this tender?"
        description={
          pendingDelete
            ? `"${tenderTitle(pendingDelete)}" and its extracted requirements, evidence matches, source PDF and output folder will be removed. This cannot be undone.`
            : ''
        }
        confirmLabel={deletingId !== null ? 'Deleting…' : 'Delete tender'}
        onConfirm={() => {
          if (pendingDelete) void performDelete(pendingDelete)
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  )
}

/**
 * One figure in the summary strip.
 *
 * Three shapes, chosen by whether the number leads anywhere: a `Link` when it
 * opens another page, a `button` when it filters this one, and a plain `div` when
 * it does neither. A tile that looks clickable and is not is worse than one that
 * plainly is not, so the hover treatment and the arrow live only on the two
 * interactive variants.
 *
 * Copied from `DocumentsOverviewPage` with one addition: an `amber` tone, so the
 * "Ready for review" tile matches its status pill exactly — amber is the tender
 * vocabulary's colour for "finished analysing, now waiting on a human", and the
 * figure should speak it too.
 */
type FigureTone = 'neutral' | 'sky' | 'amber' | 'rose'

const FIGURE_TONES: Record<FigureTone, string> = {
  neutral: 'bg-surface-muted text-neutral-600',
  sky: 'bg-sky-50 text-sky-700',
  amber: 'bg-amber-50 text-amber-700',
  rose: 'bg-rose-50 text-rose-700',
}

function SummaryFigure({
  icon,
  label,
  value,
  tone = 'neutral',
  hint,
  to,
  onSelect,
  active = false,
  actionLabel,
}: {
  icon: ReactNode
  label: string
  value: number | null
  tone?: FigureTone
  /** A second line under the label, for a breakdown the headline number hides. */
  hint?: string
  /** Navigates. Mutually exclusive with `onSelect`. */
  to?: string
  /** Filters the table in place. Mutually exclusive with `to`. */
  onSelect?: () => void
  /** Whether this tile's filter is the one currently applied. */
  active?: boolean
  /** The accessible name for the interactive variants, which the label underspecifies. */
  actionLabel?: string
}) {
  const interactive = to !== undefined || onSelect !== undefined

  const body = (
    <>
      <span
        aria-hidden="true"
        className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${FIGURE_TONES[tone]}`}
      >
        {icon}
      </span>
      <span className="min-w-0">
        {value === null ? (
          <span
            aria-hidden="true"
            className="mt-1 mb-1.5 block h-5 w-12 animate-pulse rounded-md bg-surface-muted motion-reduce:animate-none"
          />
        ) : (
          <span className="block font-display text-xl font-semibold tracking-tight text-neutral-900 tabular-nums">
            {formatCount(value)}
          </span>
        )}
        <span className="block truncate text-xs text-neutral-500">{label}</span>
        {hint ? (
          <span className="mt-0.5 block truncate text-[0.6875rem] text-neutral-400 tabular-nums">
            {hint}
          </span>
        ) : null}
      </span>
      {interactive ? (
        <ArrowRightIcon className="ml-auto size-4 shrink-0 text-neutral-400 transition-transform duration-150 group-hover:translate-x-0.5 group-hover:text-brand-600" />
      ) : null}
    </>
  )

  /* One class list for both interactive variants, so filtering and navigating are
     visibly the same kind of affordance and only the destination differs. */
  const interactiveClasses = [
    'group flex w-full items-center gap-3 px-4 py-4 text-left transition-colors duration-150 sm:px-5',
    active ? 'bg-selected hover:bg-selected' : 'bg-surface hover:bg-surface-muted',
  ].join(' ')

  if (to) {
    return (
      <Link to={to} aria-label={actionLabel} className={interactiveClasses}>
        {body}
      </Link>
    )
  }

  if (onSelect) {
    return (
      <button
        type="button"
        onClick={onSelect}
        /* `aria-pressed` rather than a second label: the tile is a toggle, and a
           screen reader should hear that the filter is on, not read new words. */
        aria-pressed={active}
        aria-label={actionLabel}
        className={interactiveClasses}
      >
        {body}
      </button>
    )
  }

  return <div className="flex items-center gap-3 bg-surface px-4 py-4 sm:px-5">{body}</div>
}
