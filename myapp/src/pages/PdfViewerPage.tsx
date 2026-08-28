/**
 * Reading one document.
 *
 * A detail view, not a fifth Documents section — so it sits outside `DocumentsLayout` and
 * gets a back link rather than the segmented control. Tabs would imply you can step
 * sideways from "the document I am reading" to "Upload" and return to the same place,
 * which is not what would happen.
 *
 * **This page shows whichever of two things is real, and both when both are.** The
 * backend serves the stored upload at `GET /documents/{id}/file`, so a PDF renders as
 * pages. Anything else — a `.docx`, a `.pptx`, a scan — has no PDF to render, and for
 * those the content is the parsed text: the chunks from
 * `GET /documents/{id}?include_chunks=true`, which are the same passages the search
 * actually matches on, with the parser's extracted figures inline. That is not a
 * consolation prize; the passages are the thing that determines what VR-Nexus can
 * answer, which is why a PDF that has been indexed offers both views behind a toggle
 * rather than hiding its text behind its own pages.
 *
 * `canRenderPages` is the single gate. It is true only for a filename ending `.pdf`,
 * because react-pdf is the only renderer here and a `.docx` handed to it fails as "this
 * file could not be opened" — which blames the document for a mismatch this page chose.
 * The file type comes from the filename rather than a field: `DocumentOut` returns no
 * `file_type`, and `fileTypeFromName` is the same extension rule the server validates
 * uploads with.
 *
 * **Nothing on this page points the browser at an API URL.** Every library route requires
 * a bearer token in the Authorization header, and a request the browser starts by itself —
 * an `<img src>`, an `<a href download>`, react-pdf fetching its own `file` prop — sends
 * no header and comes back 403. So the file, each extracted figure and the download all
 * pull bytes through the service layer and render a `blob:` URL instead, which needs no
 * network to read. That is what the small amount of effect-and-cleanup machinery in
 * `PdfPane`, `ChunkFigure` and `DownloadFileButton` is for: each one owns an object URL
 * and is responsible for revoking it.
 *
 * `react-pdf` over the alternatives: an `<iframe>` is free but hands the whole surface to
 * the browser's built-in viewer — no control over the toolbar, no way to sync a page
 * number with anything else, a different look in every browser.
 * `@react-pdf-viewer/core` brings its own design system and plugin architecture, which is
 * more than this needs and harder to make match the rest of the app. `react-pdf` is the
 * thin binding: it renders a page to a canvas and leaves the chrome to us.
 *
 * Fit-to-width is the base zoom rather than 100%. A PDF page is 612pt across, which is
 * 816px at scale 1 — wider than a phone and wider than the column this sits in, so a
 * viewer that opens at "100%" opens sideways-scrolling. Measuring the container and
 * treating that width as 1× means the first thing you see is the whole page.
 *
 * Only the current page is rendered. A twenty-page document as twenty mounted canvases
 * is tens of megabytes of bitmap for nineteen pages nobody is looking at.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Document, Page } from 'react-pdf'
import { PDF_OPTIONS } from '@/lib/pdfWorker'
import { ROUTES } from '@/constants/routes'
import { CATEGORY_LABELS, documentTitle, fileTypeFromName } from '@/models/documents'
import type { DocumentChunk, LibraryDocumentDetail } from '@/models/documents'
import {
  fetchDocumentFileObjectUrl,
  fetchDocumentImageObjectUrl,
  getDocument,
  releaseObjectUrl,
} from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { ApiError, errorMessage } from '@/lib/apiClient'
import { formatCount, formatLongDate } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { QUIET_SURFACE } from '@/components/ui/surfaces'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { TrainingStatusPill } from '@/components/documents/TrainingStatusPill'
import { FileGlyph } from '@/components/documents/FileGlyph'
import {
  AlertTriangleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  DownloadIcon,
  FileTextIcon,
  RefreshIcon,
  SparklesIcon,
  SpinnerIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from '@/components/ui/icons'

const MIN_SCALE = 0.5
const MAX_SCALE = 3
const SCALE_STEP = 0.25

/** Shared paint for the toolbar's square controls. */
const TOOL_CLASSES = [
  'inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-hairline',
  'bg-surface text-neutral-600 transition-colors duration-150',
  'hover:border-neutral-300 hover:text-neutral-900',
  'disabled:pointer-events-none disabled:opacity-40',
].join(' ')

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))
}

/**
 * Which of the two content views is showing.
 *
 * Only ever a choice for an indexed PDF. A non-PDF has no pages to render, and a PDF
 * with no chunks has no text to read, so in both of those cases the mode is decided by
 * what exists rather than by anything the reader picked.
 */
type ViewMode = 'pages' | 'text'

/**
 * Whether react-pdf has any business trying to render this upload.
 *
 * PDFs only, and the extension is the test. `DocumentOut` carries no `file_type` — the
 * table and the drop zone both work it out from the filename for the same reason — so
 * `fileTypeFromName` is the rule here too, and it is the server's own rule: extension,
 * not the browser's MIME guess.
 *
 * Handing a `.docx` to react-pdf would not degrade, it would fail, and it would fail
 * with "this file could not be opened" — a message that reads as a broken document
 * rather than a renderer being pointed at the wrong format. Anything that is not a PDF
 * gets its parsed text instead, and its Download button, which is the honest pair of
 * affordances for a file this page cannot draw.
 *
 * A predicate now, rather than the URL this used to return. The URL is fetched inside
 * `PdfPane` instead, because reading the file is an authenticated request that yields
 * bytes rather than a string anything can link to. Deciding *whether* to offer pages stays
 * a synchronous question about a filename, which is what keeps the layout below free of a
 * loading state it does not need.
 */
function canRenderPages(document: LibraryDocumentDetail): boolean {
  return fileTypeFromName(document.original_filename) === 'pdf'
}

/**
 * The Pages / Text switch, shown only when both views hold something.
 *
 * Two buttons rather than an ARIA tablist: a tablist takes over arrow keys and expects
 * `tabpanel` wiring for what is really one toggle over one region. `aria-pressed` says
 * which is on, which is what a screen reader needs here.
 */
function ViewToggle({
  mode,
  onChange,
}: {
  mode: ViewMode
  onChange: (next: ViewMode) => void
}) {
  const options: { value: ViewMode; label: string }[] = [
    { value: 'pages', label: 'Pages' },
    { value: 'text', label: 'Extracted text' },
  ]

  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-hairline bg-surface-muted p-1">
      {options.map((option) => {
        const active = option.value === mode

        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={[
              'rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors duration-150',
              active
                ? 'bg-surface text-neutral-900 shadow-sm'
                : 'text-neutral-600 hover:text-neutral-900',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/**
 * One metadata row.
 *
 * `inferred` marks a value the tagger produced rather than a person, which is the
 * difference between a sector someone typed and one a model guessed. The product uses
 * sparkles for everything the model did, so it is the same glyph here.
 *
 * An empty string is treated as no value. Every string on `DocumentOut` is a string
 * rather than null — an untagged sector arrives as `""`, not `null` — so testing for
 * null alone would print eight blank rows on an untagged document instead of eight
 * dashes.
 */
function MetaRow({
  label,
  value,
  inferred = false,
}: {
  label: string
  value: string | null
  inferred?: boolean
}) {
  const filled = value !== null && value.trim() !== ''

  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <dt className="shrink-0 text-xs font-medium text-neutral-500">{label}</dt>
      <dd className="flex min-w-0 items-center gap-1.5 text-right text-sm text-neutral-900">
        <span className="min-w-0 break-words">{filled ? value : '—'}</span>
        {inferred && filled ? (
          /* The title lives on a wrapper: every icon in this product is `aria-hidden`
             and takes only a className, which is what keeps the set consistent. A
             visible "inferred" chip on eight rows would be a second column of the same
             word, so this is a hover and a tooltip. */
          <span title="Inferred while indexing" className="flex shrink-0 text-brand-400">
            <SparklesIcon className="size-3.5" />
          </span>
        ) : null}
      </dd>
    </div>
  )
}

/**
 * A figure the parser pulled out of the document.
 *
 * `image_paths` records what the parser wrote, and the file can be gone — cleaned up,
 * moved, or never written because the parse half-failed. A broken-image glyph in the
 * middle of the prose reads as a bug in this page, so a figure that will not load
 * removes itself and leaves the text intact.
 *
 * The bytes come through `fetchDocumentImageObjectUrl` rather than from the route in an
 * `src`, because the route wants an Authorization header and an `src` cannot carry one.
 * That has a cost this component has to pay back: `loading="lazy"` only defers a fetch the
 * *browser* is making, so it stopped meaning anything here, and an IntersectionObserver
 * takes its place.
 */
function ChunkFigure({
  documentId,
  imageName,
}: {
  documentId: string
  imageName: string
}) {
  const holderRef = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(false)
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  /* Nothing is fetched until the figure is nearly on screen. Without this, opening an
     indexed tender fires one authenticated request per figure the moment the text view
     mounts — fifty of them before the reader has finished the first passage. 400px of
     margin starts the fetch just early enough that the image is usually decoded by the
     time it is scrolled to. `near` is one-way: once tripped, the observer is done. */
  useEffect(() => {
    const element = holderRef.current

    if (!element || near) {
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true)
          observer.disconnect()
        }
      },
      { rootMargin: '400px' },
    )

    observer.observe(element)

    return () => observer.disconnect()
  }, [near])

  useEffect(() => {
    if (!near) {
      return
    }

    const controller = new AbortController()
    let created: string | null = null
    let cancelled = false

    setFailed(false)

    fetchDocumentImageObjectUrl(documentId, imageName, { signal: controller.signal })
      .then((url) => {
        if (cancelled) {
          /* Resolved after the cleanup ran. The bytes are downloaded and the URL exists,
             so the only thing left worth doing is not leaking it. */
          releaseObjectUrl(url)
          return
        }

        created = url
        setObjectUrl(url)
      })
      .catch(() => {
        /* Every failure lands here and looks the same on screen: a 403 with no session, a
           404 for a file that was cleaned up, an abort from navigating away. The figure
           removes itself either way, which is the same thing the old `onError` did. */
        if (!cancelled) {
          setFailed(true)
        }
      })

    return () => {
      cancelled = true
      controller.abort()
      releaseObjectUrl(created)
      /* Cleared as well as revoked. On a dependency change this revokes the very URL the
         component is still rendering, and a dead `blob:` URL in an `src` fires `onError` —
         which would latch `failed` for a figure whose replacement is already in flight. */
      setObjectUrl(null)
    }
  }, [documentId, imageName, near])

  if (failed) {
    return null
  }

  return (
    <div ref={holderRef} className="mt-3 self-start">
      {objectUrl === null ? (
        /* A reserved box rather than nothing, so the prose does not reflow under the
           reader when the figure lands. Deliberately plain — a spinner on every figure in
           a long document is more motion than information. */
        <div
          aria-hidden="true"
          className="h-40 w-64 max-w-full animate-pulse rounded-lg border border-hairline bg-surface-muted"
        />
      ) : (
        <img
          src={objectUrl}
          alt={`Figure extracted from the document: ${imageName}`}
          onError={() => setFailed(true)}
          className="max-h-[32rem] w-auto max-w-full rounded-lg border border-hairline bg-surface"
        />
      )}
    </div>
  )
}

/**
 * The parsed document, read as prose.
 *
 * Passages are rendered in `chunk_index` order because that is the order they were cut
 * from the file; the API does not promise the array arrives sorted, and a document read
 * out of order is worse than useless.
 *
 * Structural markers adapt to what the parser actually found. A tender that came out with
 * section names gets those as headings, which is real structure from the document. One
 * that came out with none gets page markers instead. Rendering both would put two
 * competing dividers between every passage, and rendering section headings on a document
 * that has no sections would print nothing at all and leave an undifferentiated wall of
 * text.
 */
function ExtractedContent({
  documentId,
  chunks,
}: {
  documentId: string
  chunks: DocumentChunk[]
}) {
  const ordered = useMemo(
    () => [...chunks].sort((a, b) => a.chunk_index - b.chunk_index),
    [chunks],
  )

  const hasSections = useMemo(
    () => ordered.some((chunk) => chunk.section_name.trim() !== ''),
    [ordered],
  )

  if (ordered.length === 0) {
    return (
      <Panel title="Contents" description="Nothing has been extracted from this file yet.">
        <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
          <span
            aria-hidden="true"
            className="flex size-11 items-center justify-center rounded-xl bg-surface-muted text-neutral-500"
          >
            <FileTextIcon className="size-5" />
          </span>
          <p className="text-sm font-medium text-neutral-900">This document has no passages</p>
          <p className="max-w-sm text-xs leading-relaxed text-neutral-500">
            Uploading stores a file; indexing is what reads it. Until this document has
            been indexed there is no text to show here, and nothing from it can appear in
            an answer. Index it from the library to populate this page.
          </p>
          <ActionButton variant="primary" size="sm" to={ROUTES.documents} className="mt-1">
            Back to the library
          </ActionButton>
        </div>
      </Panel>
    )
  }

  return (
    <Panel
      title="Contents"
      description={`${formatCount(ordered.length)} ${
        ordered.length === 1 ? 'passage' : 'passages'
      } read out of this file — the same text the search matches on.`}
      flush
    >
      {/*
        A capped reading column rather than the full panel width. Prose set across a
        1200px panel runs to about 200 characters a line, which the eye loses track of
        between the end of one line and the start of the next; `max-w-3xl` keeps it near
        the 65-90 characters that reads comfortably. The scroll lives here so the metadata
        column beside it stays put while the document moves.
      */}
      <div className="max-h-[calc(100vh-16rem)] overflow-y-auto px-5 py-6 sm:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          {ordered.map((chunk, index) => {
            const previous = index > 0 ? ordered[index - 1] : null

            const showSection =
              hasSections &&
              chunk.section_name.trim() !== '' &&
              (previous === null || previous.section_name !== chunk.section_name)

            const showPage =
              !hasSections &&
              chunk.page_number > 0 &&
              (previous === null || previous.page_number !== chunk.page_number)

            return (
              <div key={chunk.id} className="flex flex-col">
                {showSection ? (
                  <h2 className="mt-2 mb-2 font-display text-sm font-semibold tracking-tight text-neutral-900 first:mt-0">
                    {chunk.section_name}
                    {chunk.page_number > 0 ? (
                      <span className="ml-2 font-sans text-xs font-normal text-neutral-500 tabular-nums">
                        Page {formatCount(chunk.page_number)}
                      </span>
                    ) : null}
                  </h2>
                ) : null}

                {showPage ? (
                  <p className="mt-2 mb-2 text-xs font-semibold tracking-wide text-neutral-400 tabular-nums first:mt-0">
                    Page {formatCount(chunk.page_number)}
                  </p>
                ) : null}

                {/* `whitespace-pre-wrap` because the parser keeps the document's own line
                    and paragraph breaks inside a chunk, and collapsing them runs tables
                    and bullet lists into one another. */}
                <p className="text-sm leading-relaxed whitespace-pre-wrap text-neutral-700">
                  {chunk.content}
                </p>

                {chunk.image_paths.map((imageName) => (
                  <ChunkFigure
                    key={imageName}
                    documentId={documentId}
                    imageName={imageName}
                  />
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </Panel>
  )
}

/**
 * The pane's failure card, shared by its two ways of failing.
 *
 * Fetching the bytes and rendering them are separate steps now, and either can break — a
 * 403 with no session, a 404 for a file wiped off the volume, a PDF pdf.js will not parse.
 * A reader does not care which step it was, so both say the same thing and offer the same
 * Retry, and the specific message underneath is where the difference shows.
 */
function PaneFailure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex max-w-md flex-col items-center gap-3 py-20 text-center">
      <span
        aria-hidden="true"
        className="flex size-11 items-center justify-center rounded-xl bg-rose-50 text-rose-700"
      >
        <AlertTriangleIcon className="size-5" />
      </span>
      <p className="text-sm font-medium text-neutral-900">This file could not be opened</p>
      <p className="text-xs leading-relaxed text-neutral-500">{message}</p>
      <ActionButton
        variant="secondary"
        size="sm"
        leadingIcon={<RefreshIcon />}
        onClick={onRetry}
      >
        Try again
      </ActionButton>
    </div>
  )
}

/** The pane's spinner, likewise shared. The label is what says which step is running. */
function PaneLoading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5 py-20 text-sm text-neutral-500">
      <SpinnerIcon className="size-4 animate-spin" />
      {label}
    </div>
  )
}

/**
 * The rendered file, for when there is a file to render.
 *
 * Its own component so the paging, zoom, measurement and fetch state only exists when a
 * source does. Folded into the page, those `useState`s would run on every document
 * including the ones with nothing to render.
 *
 * It takes an id rather than a URL because the file has to be *fetched*: react-pdf given a
 * URL fetches it itself and sends no Authorization header, so the only way to authenticate
 * the read is to do it here and hand react-pdf the resulting `blob:` URL.
 */
function PdfPane({ documentId }: { documentId: string }) {
  const [numPages, setNumPages] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [scale, setScale] = useState(1)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  /* Two error slots, because there are two steps. `fetchError` is this component failing
     to get the bytes; `loadError` is react-pdf failing to make sense of them. Collapsing
     them would mean a retry could not tell which step to blame. */
  const [sourceUrl, setSourceUrl] = useState<string | null>(null)
  const [fetchError, setFetchError] = useState<string | null>(null)

  /* `attempt` is in the deps, so Retry re-downloads rather than just remounting. The old
     version could only remount, which was the right fix when the failure was react-pdf
     caching a bad parse against its `file` prop — and no fix at all for a request that
     never returned bytes in the first place. */
  useEffect(() => {
    const controller = new AbortController()
    let created: string | null = null
    let cancelled = false

    setFetchError(null)
    setLoadError(null)

    fetchDocumentFileObjectUrl(documentId, { signal: controller.signal })
      .then((url) => {
        if (cancelled) {
          releaseObjectUrl(url)
          return
        }

        created = url
        setSourceUrl(url)
      })
      .catch((error: unknown) => {
        /* An abort only ever comes from the cleanup below, which sets `cancelled` first,
           so this needs no separate check for it. */
        if (!cancelled) {
          setFetchError(errorMessage(error))
        }
      })

    return () => {
      cancelled = true
      controller.abort()
      releaseObjectUrl(created)
      setSourceUrl(null)
    }
  }, [documentId, attempt])

  const retry = () => setAttempt((current) => current + 1)

  /* The width the page is drawn at. Measured rather than assumed, so fit-to-width is
     actually the width of the column it lands in — which changes with the breakpoint,
     the sidebar and the scrollbar. */
  const frameRef = useRef<HTMLDivElement>(null)
  const [frameWidth, setFrameWidth] = useState(0)

  useEffect(() => {
    const element = frameRef.current

    if (!element) {
      return
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]

      if (entry) {
        setFrameWidth(entry.contentRect.width)
      }
    })

    observer.observe(element)

    return () => observer.disconnect()
  }, [])

  const canPrev = pageNumber > 1
  const canNext = numPages > 0 && pageNumber < numPages
  const pageWidth = frameWidth > 0 ? Math.round(frameWidth * scale) : undefined

  /* The subtitle follows whichever of the three stages the pane is in, so the header and
     the body never disagree. "Rendering the file" above a spinner that is in fact still
     downloading it is a small lie, and it makes a slow network look like a slow renderer. */
  const paneDescription =
    numPages > 0
      ? `Page ${formatCount(pageNumber)} of ${formatCount(numPages)}`
      : fetchError !== null
        ? 'The file could not be read.'
        : sourceUrl === null
          ? 'Fetching the file.'
          : 'Rendering the file.'

  return (
    <Panel
      title="Pages"
      description={paneDescription}
      action={
        /*
          One toolbar, three controls, and the zoom percentage stated as a number so the
          two buttons are not the only feedback that anything happened.
        */
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => setScale((current) => clampScale(current - SCALE_STEP))}
            disabled={scale <= MIN_SCALE}
            aria-label="Zoom out"
            title="Zoom out"
            className={TOOL_CLASSES}
          >
            <ZoomOutIcon className="size-4" />
          </button>
          <button
            type="button"
            onClick={() => setScale(1)}
            aria-label="Fit the page to the width"
            title="Fit to width"
            className="inline-flex h-9 min-w-14 shrink-0 items-center justify-center rounded-lg border border-hairline bg-surface px-2 text-xs font-semibold text-neutral-700 tabular-nums transition-colors duration-150 hover:border-neutral-300 hover:text-neutral-900"
          >
            {Math.round(scale * 100)}%
          </button>
          <button
            type="button"
            onClick={() => setScale((current) => clampScale(current + SCALE_STEP))}
            disabled={scale >= MAX_SCALE}
            aria-label="Zoom in"
            title="Zoom in"
            className={TOOL_CLASSES}
          >
            <ZoomInIcon className="size-4" />
          </button>
        </div>
      }
      flush
    >
      {/*
        The scroll container is the panel body, and it is the element measured for
        fit-to-width. `overflow-auto` on both axes because zooming past 100% is exactly
        the case where horizontal scrolling is wanted.

        `safe center` rather than plain `center`, and this is the whole reason zooming
        works: a centred flex item that outgrows its scroll container overflows equally in
        both directions, and the half that spills past the start edge cannot be scrolled
        back to — zoom to 300% and the left third of every page is simply gone. `safe`
        falls back to start alignment the moment the item stops fitting, which is exactly
        when centring stops being a kindness. A browser too old to know the keyword drops
        the declaration and gets start alignment anyway, which is the same answer.
      */}
      <div
        ref={frameRef}
        className="flex min-h-[28rem] justify-center-safe overflow-auto bg-surface-muted p-4 sm:p-6"
      >
        {fetchError !== null ? (
          <PaneFailure message={fetchError} onRetry={retry} />
        ) : sourceUrl === null ? (
          <PaneLoading label="Fetching the document" />
        ) : (
          <Document
            /* Keyed on the blob URL, which is a new string on every fetch. That gives Retry
               the clean remount react-pdf needs — it caches a failed parse against the
               `file` prop — with no separate counter in the key. */
            key={sourceUrl}
            file={sourceUrl}
            options={PDF_OPTIONS}
            onLoadSuccess={(pdf) => {
              setNumPages(pdf.numPages)
              setPageNumber((current) => Math.min(current, pdf.numPages))
              setLoadError(null)
            }}
            onLoadError={(error) => setLoadError(error.message)}
            loading={<PaneLoading label="Opening the document" />}
            error={
              <PaneFailure
                message={
                  loadError ??
                  'The file is missing, or it is not a PDF the renderer can read.'
                }
                onRetry={retry}
              />
            }
            /* No visible file name in react-pdf's own strings; everything a reader sees on
               this page is written above. */
            noData={<p className="py-20 text-sm text-neutral-500">No file to display.</p>}
          >
            <Page
              pageNumber={pageNumber}
              width={pageWidth}
              /* A canvas on a light grey field needs its own edge, or the page and the
                 surround read as one shape. */
              className="overflow-hidden rounded-lg border border-hairline bg-surface shadow-sm"
              loading={
                <div className="flex h-[28rem] items-center gap-2.5 text-sm text-neutral-500">
                  <SpinnerIcon className="size-4 animate-spin" />
                  Rendering page {formatCount(pageNumber)}
                </div>
              }
            />
          </Document>
        )}
      </div>

      {/*
        Paging lives under the page, where the eye already is when it reaches the end of
        one. Both buttons keep their labels from `sm` up — "Previous" and "Next" are
        shorter to read than a chevron is to interpret.
      */}
      <div className="flex items-center justify-between gap-3 border-t border-hairline px-4 py-3">
        <ActionButton
          variant="secondary"
          size="sm"
          leadingIcon={<ChevronLeftIcon />}
          disabled={!canPrev}
          onClick={() => setPageNumber((current) => Math.max(1, current - 1))}
          hideLabelOnMobile
        >
          Previous
        </ActionButton>

        <p className="text-xs font-medium text-neutral-600 tabular-nums">
          {numPages > 0 ? `${formatCount(pageNumber)} / ${formatCount(numPages)}` : '—'}
        </p>

        <ActionButton
          variant="secondary"
          size="sm"
          trailingIcon={<ChevronRightIcon />}
          disabled={!canNext}
          onClick={() => setPageNumber((current) => Math.min(numPages, current + 1))}
          hideLabelOnMobile
        >
          Next
        </ActionButton>
      </div>
    </Panel>
  )
}

/**
 * Download, which is a fetch now rather than a link.
 *
 * `<a href download>` was the right answer while the route was open: the browser did the
 * request, the progress and the save dialog, and `download` was also what overrode the
 * route's inline disposition so the same URL could preview in a tab and save from here. It
 * stopped being an option when the route started requiring a bearer token, because a
 * browser sends none on a navigation and the reader would get a 403 body saved to disk
 * under the document's name.
 *
 * So this does what the browser would have done, in order: fetch the bytes, point a
 * throwaway anchor at the object URL, click it, revoke. `window.document` and not
 * `document`, because the page component below binds `document` to the library row — the
 * shadowing is real and this is the one place in the file that needs the global.
 */
function DownloadFileButton({
  documentId,
  filename,
}: {
  documentId: string
  filename: string
}) {
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const save = async () => {
    if (busy) {
      return
    }

    setBusy(true)
    setFailure(null)

    try {
      /* Deliberately no AbortSignal. A download is not tied to the reader still looking at
         this page — they asked for the file, and navigating away a moment later should not
         cancel it. The object URL is revoked on every path below regardless. */
      const url = await fetchDocumentFileObjectUrl(documentId)

      const anchor = window.document.createElement('a')
      anchor.href = url
      anchor.download = filename
      /* Attached before the click and removed after: a detached anchor's synthetic click
         does nothing in Firefox. */
      window.document.body.append(anchor)
      anchor.click()
      anchor.remove()

      /* Revoked on the next task rather than in this one. The click starts the save
         synchronously, but revoking in the same tick has raced it in some browsers, and one
         timeout is a cheap way not to care which. */
      window.setTimeout(() => releaseObjectUrl(url), 0)
    } catch (error) {
      setFailure(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <button
        type="button"
        onClick={save}
        disabled={busy}
        className={[
          'inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg px-2.5',
          'text-xs font-medium whitespace-nowrap transition-all duration-150',
          'focus-visible:outline-brand-300 disabled:pointer-events-none disabled:opacity-60',
          QUIET_SURFACE,
        ].join(' ')}
      >
        {busy ? (
          <SpinnerIcon className="size-3.5 animate-spin" />
        ) : (
          <DownloadIcon className="size-3.5" />
        )}
        {busy ? 'Preparing' : 'Download'}
      </button>

      {/* `role="status"` so the failure is announced rather than only seen. It sits under
          the button instead of in a toast because it belongs to this one action, and the
          reader's next move is to press it again. */}
      {failure !== null ? (
        <p
          role="status"
          className="max-w-60 text-xs leading-relaxed text-rose-700 sm:text-right"
        >
          {failure}
        </p>
      ) : null}
    </div>
  )
}

/** The back link. Its own row above the title, so the h1 stays the first thing read. */
function BackLink() {
  return (
    <div>
      <Link
        to={ROUTES.documents}
        className="inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-neutral-600 transition-colors hover:text-neutral-900"
      >
        <ChevronLeftIcon className="size-4" />
        Documents
      </Link>
    </div>
  )
}

export function PdfViewerPage() {
  const { documentId } = useParams<{ documentId: string }>()

  /* Declared up here because a hook cannot sit behind the early returns below. This is
     the reader's *preference*, not the mode that renders — what actually renders is
     derived further down from what the document has, so a non-PDF or an unindexed file
     needs no effect to keep this in step and no state to reset. */
  const [viewMode, setViewMode] = useState<ViewMode>('pages')

  /*
   * `include_chunks` is on here and nowhere else. It is the one screen that renders the
   * passages, and it is exactly the read the service layer warns is expensive — a long
   * tender is hundreds of chunks of full text. Paying that on a page whose whole job is
   * to show them is the right trade; paying it to render a count is not.
   *
   * A missing id is rejected rather than requested. The route always supplies one, so
   * this is unreachable in practice, but sending `documents/` with an empty id would hit
   * the *list* endpoint and quietly parse an array as a document.
   */
  const detail = useAsyncData(
    (signal) =>
      documentId
        ? getDocument(documentId, true, { signal })
        : Promise.reject(new ApiError('This link has no document id.', 404, null)),
    [documentId],
  )

  const document = detail.data

  if (detail.notFound) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        <BackLink />
        <Panel title="Document not found" description="Nothing in the library has that id.">
          <div className="flex flex-col items-start gap-4">
            <p className="text-sm leading-relaxed text-neutral-600">
              The document may have been deleted, or the link may be from an older version
              of the library. The library listing shows everything that is currently
              stored.
            </p>
            <ActionButton
              variant="primary"
              to={ROUTES.documents}
              leadingIcon={<ChevronLeftIcon />}
            >
              Back to the library
            </ActionButton>
          </div>
        </Panel>
      </div>
    )
  }

  if (detail.status === 'error' && document === null) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        <BackLink />
        <Panel title="Document">
          <ErrorBlock
            title="This document could not be read"
            message={detail.error ?? 'The request did not complete.'}
            offline={detail.offline}
            onRetry={detail.refetch}
          />
        </Panel>
      </div>
    )
  }

  if (document === null) {
    return (
      <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
        <BackLink />
        <Panel title="Document" description="Reading the document.">
          <LoadingRows rows={6} label="Loading the document" />
        </Panel>
      </div>
    )
  }

  /* The download is offered for every document, because every document has a stored
     file. The PDF pane is not: `showsPages` is false for anything react-pdf cannot draw. */
  const showsPages = canRenderPages(document)

  /* Which view is live. A non-PDF has no pages, and a PDF nobody has indexed has no
     passages, so the toggle only appears when both halves hold something — and when it
     does not appear, the mode is whichever half is real. */
  const hasText = document.chunks.length > 0
  const canToggle = showsPages && hasText
  const mode: ViewMode = !showsPages ? 'text' : canToggle ? viewMode : 'pages'

  /* Real figures only. The old version printed a file size from a `size_bytes` the API
     has never returned; page and passage counts are on `DocumentOut` and are what someone
     reading this actually wants to know. */
  const facts = [
    document.page_count > 0
      ? `${formatCount(document.page_count)} ${document.page_count === 1 ? 'page' : 'pages'}`
      : null,
    document.chunk_count > 0
      ? `${formatCount(document.chunk_count)} ${
          document.chunk_count === 1 ? 'passage' : 'passages'
        }`
      : null,
  ].filter((fact): fact is string => fact !== null)

  return (
    <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
      <BackLink />

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <FileGlyph filename={document.original_filename} />
          <div className="min-w-0">
            <h1 className="font-display text-xl font-semibold tracking-tight break-words text-neutral-900 sm:text-2xl">
              {documentTitle(document)}
            </h1>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-neutral-500">
              <span className="break-all">{document.original_filename}</span>
              {facts.map((fact) => (
                <span key={fact} className="flex items-center gap-x-2">
                  <span aria-hidden="true">·</span>
                  <span className="tabular-nums">{fact}</span>
                </span>
              ))}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <TrainingStatusPill status={document.training_status} />
          {/*
            Offered for every document, since every row has a stored file — if the bytes
            have been wiped from the volume the route answers 404 and the button says so,
            which is the truth. `DownloadFileButton` explains why this is no longer the
            anchor with `download` that it wants to be.
          */}
          <DownloadFileButton
            documentId={document.id}
            filename={document.original_filename}
          />
        </div>
      </header>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {canToggle ? <ViewToggle mode={mode} onChange={setViewMode} /> : null}

          {mode === 'pages' && showsPages ? (
            <PdfPane documentId={document.id} />
          ) : (
            <ExtractedContent documentId={document.id} chunks={document.chunks} />
          )}
        </div>

        <div className="flex w-full flex-col gap-4 xl:max-w-sm">
          <Panel title="Details" description={CATEGORY_LABELS[document.category]}>
            <dl className="divide-y divide-hairline">
              <MetaRow
                label="Type"
                value={document.doc_type}
                inferred={document.auto_tagged_fields.includes('doc_type')}
              />
              <MetaRow
                label="Client"
                value={document.client}
                inferred={document.auto_tagged_fields.includes('client')}
              />
              <MetaRow
                label="Sector"
                value={document.sector}
                inferred={document.auto_tagged_fields.includes('sector')}
              />
              <MetaRow
                label="Service line"
                value={document.service_line}
                inferred={document.auto_tagged_fields.includes('service_line')}
              />
              <MetaRow
                label="Geography"
                value={document.geography}
                inferred={document.auto_tagged_fields.includes('geography')}
              />
              <MetaRow label="Uploaded" value={formatLongDate(document.created_at)} />
              <MetaRow
                label="Indexed"
                value={document.indexed_at ? formatLongDate(document.indexed_at) : null}
              />
              <MetaRow
                label="Pages"
                value={document.page_count > 0 ? formatCount(document.page_count) : null}
              />
              <MetaRow
                label="Passages"
                value={document.chunk_count > 0 ? formatCount(document.chunk_count) : null}
              />
            </dl>

            {document.keywords.length > 0 ? (
              <div className="mt-4 border-t border-hairline pt-4">
                <p className="text-xs font-medium text-neutral-500">Keywords</p>
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {document.keywords.map((keyword) => (
                    <li
                      key={keyword}
                      className="rounded-full border border-hairline bg-surface-muted px-2.5 py-1 text-xs text-neutral-700"
                    >
                      {keyword}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </Panel>

          {/* A failed document's error is the reason someone opened this page. It is not
              tucked into the metadata list. Rose rather than brand red: red is the logo
              and the primary action here, so a red panel would read as the most
              encouraged thing on screen. */}
          {document.training_error.trim() ? (
            <div className="flex items-start gap-2.5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3.5">
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-rose-700" />
              <div className="min-w-0">
                <p className="text-sm font-semibold text-rose-900">Indexing failed</p>
                <p className="mt-1 text-xs leading-relaxed break-words text-rose-800">
                  {document.training_error}
                </p>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
