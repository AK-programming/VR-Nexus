/**
 * The library listing — the Documents module's front door.
 *
 * Four things happen here and nothing else: you find a document, you see how far
 * through indexing it is, you send it (or several) to be indexed, or you remove it.
 * Reading a document is the viewer's job and adding one is Upload's, so neither is
 * duplicated on this page — the row title links to the first and the header button to
 * the second.
 *
 * **Where the numbers come from.** Rows are `GET /documents`; the four figures at the
 * top are `GET /stats`. Two reads rather than one because they answer different
 * questions: the table shows the current filter, the strip shows the whole library. The
 * earlier version of this page counted statuses by reducing over the rows it happened to
 * be holding, which meant the strip silently described one page of results and called it
 * the library.
 *
 * **Category and status filter on the server; search filters here.** That split is not
 * arbitrary — it is exactly what the API supports. `category` and `status` are real query
 * parameters, so sending them means a filtered read of the *whole* library rather than a
 * filtered view of the first page. There is no text-search parameter, so the search box
 * works over the rows already fetched, and `WINDOW_ADVISORY` below says so out loud when
 * the window is full instead of quietly returning half an answer.
 *
 * **Every mutation refetches.** No local status patching. The old page set a row to
 * `queued` in React state after a successful retrain, which looked responsive and lied in
 * two ways: it kept the row visible under a filter that now excluded it, and it invented
 * a status the server might not have moved to. A refetch costs one request and is right.
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ROUTES, documentViewerPath } from '@/constants/routes'
import {
  CATEGORY_LABELS,
  DOCUMENT_CATEGORIES,
  TRAINING_STATUSES,
  TRAINING_STATUS_LABELS,
  documentTitle,
  isInFlight,
  rollUpStats,
} from '@/models/documents'
import type {
  DocumentCategory,
  DocumentTrainingStatus,
  LibraryDocument,
} from '@/models/documents'
import {
  deleteDocument,
  getStats,
  listDocuments,
  retrainDocument,
  train,
} from '@/services/documentService'
import { ApiError, errorMessage } from '@/lib/apiClient'
import { formatCount, formatShortDate } from '@/lib/formatting'
import { useAsyncData } from '@/hooks/useAsyncData'
import { Panel } from '@/components/dashboard/Panel'
import { DataTable, TableEmptyState } from '@/components/ui/DataTable'
import type { Column } from '@/components/ui/DataTable'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import type { AlertTone } from '@/components/feedback/AlertMessage'
import {
  AsyncSection,
  ErrorBlock,
  LoadingRows,
  StaleDataNotice,
} from '@/components/feedback/DataState'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { TrainingStatusPill } from '@/components/documents/TrainingStatusPill'
import {
  ArrowRightIcon,
  CheckCircleIcon,
  ClockIcon,
  DatabaseIcon,
  FileTextIcon,
  RefreshIcon,
  SearchIcon,
  SpinnerIcon,
  TrashIcon,
  UploadIcon,
  XCircleIcon,
} from '@/components/ui/icons'

/** `all` is a filter value, not a category, so the two unions are kept separate. */
type CategoryFilter = DocumentCategory | 'all'
type StatusFilter = DocumentTrainingStatus | 'all'

type Notice = { tone: AlertTone; text: string } | null

/** What the delete dialog is about to remove. `null` closes it. */
type DeleteTarget = { ids: string[]; label: string } | null

/**
 * How many rows one read pulls.
 *
 * The server allows up to 500 and defaults to 100. 200 is chosen rather than the maximum
 * because `GET /documents` returns a bare array with no total and no cursor — there is no
 * pagination metadata to page with — so this number is a window, and a window is only
 * honest if the page admits where its edge is. Filters move the window; they do not
 * enlarge it.
 */
const PAGE_SIZE = 200

/** Shared field paint, so the search box and both selects are visibly one control set. */
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
 * Title *and* filename, because people remember a document either way — and the two
 * genuinely differ here ("Telehealth Plathform.pdf" is titled "AgeMD Telehealth
 * Platform", typo included, which is exactly the case a title-only search misses).
 * Client, sector and keywords are in because "show me the logistics work" is the
 * question this library exists to answer.
 *
 * No `?? ''` on any of these any more: the server's validators coerce NULL to `""`, so
 * every one of them is a string. The fallbacks that used to be here implied a
 * nullability the API does not have.
 */
function searchHaystack(document: LibraryDocument): string {
  return [
    document.title,
    document.original_filename,
    document.client,
    document.sector,
    document.service_line,
    document.geography,
    document.doc_type,
    document.keywords.join(' '),
  ]
    .join(' ')
    .toLowerCase()
}

export function DocumentsOverviewPage() {
  const navigate = useNavigate()

  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<CategoryFilter>('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [notice, setNotice] = useState<Notice>(null)
  const [busy, setBusy] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null)

  /*
   * `category` and `status` are in the dependency list, so changing either re-reads from
   * the server. The hook keeps the current rows on screen and raises `isRefreshing`
   * rather than dropping to a skeleton, and it aborts the previous request — which is
   * what stops a slow "All categories" response from landing on top of a fast
   * "Methodology" one.
   *
   * `undefined` rather than the string 'all' for the cleared case: `listDocuments` drops
   * undefined parameters, and `?category=all` is a 422 from FastAPI's enum coercion, not
   * an absent filter.
   */
  const library = useAsyncData(
    (signal) =>
      listDocuments(
        {
          category: category === 'all' ? undefined : category,
          status: status === 'all' ? undefined : status,
          limit: PAGE_SIZE,
        },
        { signal },
      ),
    [category, status],
  )

  /* No dependencies: the totals describe the library, so a filter change must not
     disturb them. Refetched explicitly after anything that adds or removes a document. */
  const stats = useAsyncData((signal) => getStats({ signal }), [])

  const documents = useMemo(() => library.data ?? [], [library.data])
  const rollup = useMemo(() => (stats.data ? rollUpStats(stats.data) : null), [stats.data])

  const filtersActive = query.trim() !== '' || category !== 'all' || status !== 'all'

  /* Only the search runs here. Category and status were applied by the server, so
     re-applying them would be dead code that quietly disagrees with the request. */
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()

    if (needle === '') {
      return documents
    }

    return documents.filter((document) => searchHaystack(document).includes(needle))
  }, [documents, query])

  /* Selection is held as ids, so it survives sorting and filtering — but the buttons
     act only on what is still on screen, matching what the header checkbox ticks. */
  const visibleIds = useMemo(() => new Set(visible.map((document) => document.id)), [visible])
  const actionableIds = selectedIds.filter((id) => visibleIds.has(id))

  /** The window is full, so there may be documents the search below cannot see. */
  const windowFull = documents.length >= PAGE_SIZE

  function refreshAll() {
    library.refetch()
    stats.refetch()
  }

  /** Toggles a status tile in the strip into and out of the status filter. */
  function toggleStatus(next: DocumentTrainingStatus) {
    setStatus((current) => (current === next ? 'all' : next))
    /* The tile promises "these documents". A search left in the box would silently
       narrow that further and make the count disagree with the tile that was clicked. */
    setQuery('')
    setNotice(null)
  }

  async function handleTrain(ids: string[]) {
    setBusy(true)
    setNotice(null)

    try {
      const response = await train(ids)

      /* `skipped` is not a failure — it is what pressing Train twice returns, and what
         an already-indexed document returns without `force`. Reporting it as an error
         would make the ordinary case look broken. */
      const skipped = response.skipped.length

      setSelectedIds([])

      const firstJob = response.jobs[0]

      if (firstJob) {
        /* Straight to Processing, where the socket is. Refetching this page's rows first
           would be a request whose response arrives after the page has unmounted. */
        navigate(`${ROUTES.documentsProcessing}?job=${firstJob.id}`)
        return
      }

      refreshAll()
      setNotice({
        tone: 'info',
        text:
          skipped > 0
            ? `Nothing to queue - ${formatCount(skipped)} ${
                skipped === 1 ? 'document is' : 'documents are'
              } already indexed or in progress.`
            : 'Nothing to queue.',
      })
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  async function handleRetrain(document: LibraryDocument) {
    setBusy(true)
    setNotice(null)

    try {
      const job = await retrainDocument(document.id)
      navigate(`${ROUTES.documentsProcessing}?job=${job.id}`)
    } catch (error) {
      /* 409 here means a worker already holds this document — a "not now", not a
         failure. Painting it red would teach people to distrust red. */
      const conflict = error instanceof ApiError && error.status === 409

      setNotice({
        tone: conflict ? 'warning' : 'error',
        text: conflict
          ? `${documentTitle(document)} is already being indexed. Watch it on the Processing page.`
          : errorMessage(error),
      })

      if (conflict) {
        refreshAll()
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleDeleteConfirmed() {
    if (!deleteTarget) {
      return
    }

    const { ids, label } = deleteTarget
    setDeleteTarget(null)
    setBusy(true)
    setNotice(null)

    /* Sequential rather than Promise.all: a bulk delete of forty documents should not
       open forty connections, and if the third one fails the first two have genuinely
       gone — which the count below reports accurately instead of claiming the whole
       operation failed. */
    let removed = 0

    try {
      for (const id of ids) {
        await deleteDocument(id)
        removed += 1
      }

      setSelectedIds((current) => current.filter((id) => !ids.includes(id)))
      setNotice({ tone: 'success', text: `${label} deleted.` })
    } catch (error) {
      setNotice({
        tone: 'error',
        text:
          removed > 0
            ? `${formatCount(removed)} of ${formatCount(ids.length)} deleted, then it stopped: ${errorMessage(error)}`
            : errorMessage(error),
      })
    } finally {
      /* Outside the try, because a partial delete changed the library just as much as a
         complete one and the table must not keep showing rows that are gone. */
      refreshAll()
      setBusy(false)
    }
  }

  function clearFilters() {
    setQuery('')
    setCategory('all')
    setStatus('all')
  }

  const columns: Column<LibraryDocument>[] = [
    {
      id: 'document',
      header: 'Document',
      sortValue: (document) => documentTitle(document),
      cell: (document) => (
        <div className="flex min-w-0 items-center gap-3">
          <FileGlyph filename={document.original_filename} />
          <div className="min-w-0">
            {/* The link is in the cell rather than on the row: a clickable row that
                also holds Delete needs stopPropagation on every button in it, and
                missing one deletes a document *and* navigates away. */}
            <Link
              to={documentViewerPath(document.id)}
              className="block truncate font-medium text-neutral-900 hover:text-brand-700"
            >
              {documentTitle(document)}
            </Link>
            <p className="truncate text-xs text-neutral-500">{document.original_filename}</p>
          </div>
        </div>
      ),
    },
    {
      id: 'category',
      header: 'Category',
      className: 'hidden lg:table-cell',
      sortValue: (document) => CATEGORY_LABELS[document.category],
      cell: (document) => (
        <span className="whitespace-nowrap">{CATEGORY_LABELS[document.category]}</span>
      ),
    },
    {
      id: 'client',
      header: 'Client',
      className: 'hidden xl:table-cell',
      sortValue: (document) => document.client,
      cell: (document) =>
        document.client ? (
          <span className="block max-w-[16rem] truncate">{document.client}</span>
        ) : (
          <span className="text-neutral-400">-</span>
        ),
    },
    {
      id: 'status',
      header: 'Status',
      /* Sorted by pipeline position, not alphabetically: "Embedding, Failed, Parsing,
         Queued, Ready, Tagging" is an ordering of the words, not of the work. */
      sortValue: (document) => TRAINING_STATUSES.indexOf(document.training_status),
      cell: (document) => (
        <div className="flex flex-col items-start gap-1">
          <TrainingStatusPill status={document.training_status} />
          {/*
            The reason it failed, in the row, where the failure is. `training_error` is
            real and always populated on a failed document, and the alternative is
            sending someone to another page to find out that a PDF was password
            protected. Truncated to one line with the full text on hover, because these
            come back as Python exception strings and some of them are long.
          */}
          {document.training_status === 'failed' && document.training_error ? (
            <span
              title={document.training_error}
              className="block max-w-[14rem] truncate text-xs text-rose-700 dark:text-rose-300"
            >
              {document.training_error}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      id: 'passages',
      header: 'Passages',
      className: 'hidden md:table-cell',
      numeric: true,
      /*
        This column used to be Size, reading a `size_bytes` the API has never returned —
        which is why this page could only ever be rendered against fixtures. `chunk_count`
        is real, and it answers a better question: a document with zero passages is not
        searchable no matter what its status pill says.
      */
      sortValue: (document) => document.chunk_count,
      cell: (document) =>
        document.chunk_count > 0 ? (
          formatCount(document.chunk_count)
        ) : (
          <span className="text-neutral-400">-</span>
        ),
    },
    {
      id: 'uploaded',
      header: 'Uploaded',
      className: 'hidden sm:table-cell',
      /* ISO-8601 sorts chronologically as a string, so no Date parsing per comparison. */
      sortValue: (document) => document.created_at,
      cell: (document) => (
        <time dateTime={document.created_at} className="whitespace-nowrap">
          {formatShortDate(document.created_at)}
        </time>
      ),
    },
  ]

  /** "12 of 340 documents" while filtering, the plain total otherwise. */
  const panelDescription = (() => {
    if (rollup === null) {
      return `${formatCount(visible.length)} ${visible.length === 1 ? 'document' : 'documents'}`
    }
    if (filtersActive) {
      return `${formatCount(visible.length)} of ${formatCount(rollup.total)} documents`
    }
    return `${formatCount(rollup.total)} ${rollup.total === 1 ? 'document' : 'documents'}`
  })()

  return (
    <>
      <div className="flex flex-col gap-4">
        {/*
          One box with four figures rather than four cards — the same combined shape the
          dashboard's Quick Actions bar uses, icon left and text right. These are plain
          counts with no month-on-month movement behind them, so `StatCard` would have
          to be handed a trend that does not exist.

          The separators are `gap-px` over a hairline background rather than
          `divide-x`: that draws a line between every neighbour in both the 2×2 at
          375px and the 1×4 from `sm`, where a divide utility only ever handles one
          axis and leaves the mobile grid with no seam down the middle.
        */}
        {stats.status === 'error' && rollup === null ? (
          <div className="flex flex-col gap-2 rounded-2xl border border-hairline bg-surface px-5 py-4 shadow-sm sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-neutral-600">
              Library totals unavailable. {stats.error}
            </p>
            <ActionButton variant="secondary" size="sm" onClick={stats.refetch}>
              Retry
            </ActionButton>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-hairline bg-hairline shadow-sm sm:grid-cols-4">
            <SummaryFigure
              icon={<FileTextIcon className="size-4.5" />}
              label="Documents"
              value={rollup?.total ?? null}
            />
            <SummaryFigure
              icon={<CheckCircleIcon className="size-4.5" />}
              label="Ready to search"
              value={rollup?.indexed ?? null}
              tone="emerald"
              onSelect={rollup && rollup.indexed > 0 ? () => toggleStatus('indexed') : undefined}
              active={status === 'indexed'}
              actionLabel="Show only documents that are ready to search"
            />
            <SummaryFigure
              icon={<ClockIcon className="size-4.5" />}
              label="In progress"
              value={rollup?.active ?? null}
              tone="sky"
              /*
                The one tile that leaves the page, because watching a job is what the
                Processing screen is for. Its hint keeps `queued` and `processing`
                apart — "nothing has picked these up" and "a worker is on them" have
                different causes, and a single merged number hides a stalled queue.
              */
              hint={
                rollup && rollup.active > 0
                  ? `${formatCount(rollup.processing)} running · ${formatCount(rollup.queued)} waiting`
                  : undefined
              }
              to={rollup && rollup.active > 0 ? ROUTES.documentsProcessing : undefined}
            />
            <SummaryFigure
              icon={<XCircleIcon className="size-4.5" />}
              label="Failed"
              value={rollup?.failed ?? null}
              tone="rose"
              onSelect={rollup && rollup.failed > 0 ? () => toggleStatus('failed') : undefined}
              active={status === 'failed'}
              actionLabel="Show only documents that failed to index"
            />
          </div>
        )}

        {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

        <Panel
          title="Library"
          description={panelDescription}
          action={
            <div className="flex shrink-0 items-center gap-2">
              <IconAction
                label="Refresh the library"
                icon={library.isRefreshing ? <SpinnerIcon className="animate-spin" /> : <RefreshIcon />}
                disabled={busy || library.isRefreshing}
                onClick={refreshAll}
              />
              <ActionButton
                to={ROUTES.documentsUpload}
                variant="primary"
                leadingIcon={<UploadIcon />}
              >
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
              <label htmlFor="library-search" className="sr-only">
                Search documents
              </label>
              <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-neutral-400" />
              <input
                id="library-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by title, client, sector or keyword"
                className={[...CONTROL_CLASSES, 'pr-3.5 pl-10 placeholder:text-neutral-400'].join(' ')}
              />
            </div>

            <div className="flex flex-col gap-3 sm:flex-row lg:shrink-0">
              {/* relative: gives the sr-only label a containing block of its own
                  rather than the document root - see AiAssistantPage.tsx's
                  composer for what happens without one. */}
              <div className="relative sm:w-44">
                <label htmlFor="library-category" className="sr-only">
                  Filter by category
                </label>
                <select
                  id="library-category"
                  value={category}
                  onChange={(event) => setCategory(event.target.value as CategoryFilter)}
                  className={[...CONTROL_CLASSES, 'px-3'].join(' ')}
                >
                  <option value="all">All categories</option>
                  {DOCUMENT_CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {CATEGORY_LABELS[value]}
                    </option>
                  ))}
                </select>
              </div>

              <div className="relative sm:w-40">
                <label htmlFor="library-status" className="sr-only">
                  Filter by status
                </label>
                <select
                  id="library-status"
                  value={status}
                  onChange={(event) => setStatus(event.target.value as StatusFilter)}
                  className={[...CONTROL_CLASSES, 'px-3'].join(' ')}
                >
                  <option value="all">Any status</option>
                  {TRAINING_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {TRAINING_STATUS_LABELS[value]}
                    </option>
                  ))}
                </select>
              </div>

              {/* Only rendered when there is something to clear, so the bar does not
                  carry a permanently dead button. */}
              {filtersActive ? (
                <ActionButton variant="secondary" onClick={clearFilters}>
                  Clear
                </ActionButton>
              ) : null}
            </div>
          </div>

          {/* A refresh that failed over rows that are still on screen. The rows below
              were true a moment ago, so they stay; only the claim of freshness goes. */}
          {library.status === 'error' && library.data !== null ? (
            <StaleDataNotice
              message={library.error ?? 'The last refresh did not complete.'}
              onRetry={library.refetch}
            />
          ) : null}

          {/*
            The selection bar replaces nothing and pushes nothing around — it appears
            between the filters and the table, which is where the reader's eye already
            is after ticking a box.
          */}
          {actionableIds.length > 0 ? (
            <div className="flex flex-col gap-3 border-b border-hairline bg-selected px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm font-medium text-neutral-800">
                {formatCount(actionableIds.length)} selected
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <ActionButton
                  variant="primary"
                  size="sm"
                  leadingIcon={<DatabaseIcon />}
                  disabled={busy}
                  onClick={() => void handleTrain(actionableIds)}
                >
                  Index selected
                </ActionButton>
                <ActionButton
                  variant="danger"
                  size="sm"
                  leadingIcon={<TrashIcon />}
                  disabled={busy}
                  onClick={() =>
                    setDeleteTarget({
                      ids: actionableIds,
                      label: `${formatCount(actionableIds.length)} ${
                        actionableIds.length === 1 ? 'document' : 'documents'
                      }`,
                    })
                  }
                >
                  Delete selected
                </ActionButton>
                <ActionButton variant="secondary" size="sm" onClick={() => setSelectedIds([])}>
                  Clear
                </ActionButton>
              </div>
            </div>
          ) : null}

          <AsyncSection
            status={library.status}
            /* `data !== null`, not `length > 0`: an empty array is a successful read of
               an empty library and belongs in the empty state, not under a skeleton. */
            hasData={library.data !== null}
            loading={<LoadingRows rows={6} label="Loading documents" />}
            error={
              <ErrorBlock
                title="The library could not be loaded"
                message={library.error ?? 'The request did not complete.'}
                offline={library.offline}
                onRetry={library.refetch}
              />
            }
          >
            <DataTable
              rows={visible}
              columns={columns}
              rowKey={(document) => document.id}
              caption="Documents in the evidence library"
              initialSort={{ columnId: 'uploaded', direction: 'desc' }}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              selectionLabel={(document) => `Select ${documentTitle(document)}`}
              rowClassName={(document) =>
                document.training_status === 'failed' && !selectedIds.includes(document.id)
                  ? 'bg-rose-50/40'
                  : ''
              }
              rowActions={(document) => (
                <div className="flex items-center justify-end gap-1">
                  <IconAction
                    label={
                      document.training_status === 'failed'
                        ? `Retry indexing ${documentTitle(document)}`
                        : `Re-index ${documentTitle(document)}`
                    }
                    icon={<RefreshIcon />}
                    /* The server returns 409 for a document a worker already holds, so
                       the button is closed for exactly the cases it would refuse. */
                    disabled={busy || isInFlight(document.training_status)}
                    onClick={() => void handleRetrain(document)}
                  />
                  <IconAction
                    label={`Delete ${documentTitle(document)}`}
                    icon={<TrashIcon />}
                    tone="danger"
                    disabled={busy}
                    onClick={() =>
                      setDeleteTarget({
                        ids: [document.id],
                        label: documentTitle(document),
                      })
                    }
                  />
                </div>
              )}
              empty={
                filtersActive ? (
                  <TableEmptyState
                    icon={<SearchIcon className="size-5" />}
                    title="No documents match"
                    description="Nothing in the library fits that combination of search, category and status."
                    action={
                      <ActionButton variant="secondary" size="sm" onClick={clearFilters}>
                        Clear filters
                      </ActionButton>
                    }
                  />
                ) : (
                  <TableEmptyState
                    icon={<FileTextIcon className="size-5" />}
                    title="The library is empty"
                    description="Add case studies, methodologies and company documents, and VR-Nexus will draw on them when it answers a tender."
                    action={
                      <ActionButton
                        to={ROUTES.documentsUpload}
                        variant="primary"
                        size="sm"
                        leadingIcon={<UploadIcon />}
                      >
                        Upload documents
                      </ActionButton>
                    }
                  />
                )
              }
            />

            {/*
              Where the window ends, stated rather than implied. `GET /documents` returns
              a bare array with no total, so the only honest thing a client can say when
              it asked for 200 and got 200 is that there may be more — and the fix is a
              filter, which reaches the whole library because category and status are
              applied on the server.
            */}
            {windowFull ? (
              <p className="border-t border-hairline bg-surface-muted px-5 py-3 text-xs text-neutral-500">
                Showing the {formatCount(PAGE_SIZE)} most recent
                {rollup ? ` of ${formatCount(rollup.total)}` : ''}. Filter by category or
                status to search the rest of the library.
              </p>
            ) : null}
          </AsyncSection>
        </Panel>
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete from the library?"
        description={
          deleteTarget
            ? `${deleteTarget.label} will be removed, along with every parsed passage and embedding. This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        onConfirm={() => void handleDeleteConfirmed()}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  )
}

/**
 * One figure in the summary strip.
 *
 * Three shapes, and which one it takes depends on whether the number leads anywhere:
 * a `Link` when it opens another page, a `button` when it filters this one, and a plain
 * `div` when it does neither. A tile that looks clickable and is not is worse than one
 * that plainly is not, so the hover treatment and the arrow only exist on the two
 * interactive variants.
 *
 * `value` is null until `/stats` answers, and renders as a bar rather than a 0. Showing
 * zero while loading states something false, and the difference between "no failures"
 * and "not known yet" is exactly what someone scanning this strip is reading it for.
 */
type FigureTone = 'neutral' | 'emerald' | 'sky' | 'rose'

const FIGURE_TONES: Record<FigureTone, string> = {
  neutral: 'bg-surface-muted text-neutral-600',
  emerald: 'bg-emerald-50 text-emerald-700',
  sky: 'bg-sky-50 text-sky-700',
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
  /** The accessible name for the interactive variants, which the label alone underspecifies. */
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
           screen reader should hear that the filter is on, not read different words. */
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
