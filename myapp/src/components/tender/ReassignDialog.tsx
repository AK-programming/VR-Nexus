/**
 * Pick a different library document to answer a requirement.
 *
 * The reviewer rejected the machine's pick, or there was none, and knows which
 * case study actually covers this clause. Reassigning a match repoints it at that
 * document and marks it REASSIGNED — the same accepted-evidence weight the report
 * counts, but chosen by a person.
 *
 * Built on the native `<dialog>` opened with `showModal()`, exactly like
 * `ConfirmDialog`, for the focus trap, Escape-to-close, inert background and top
 * layer that come with it for free. The library list is read once when the dialog
 * opens (not on every keystroke) and filtered client-side — the catalogue is a few
 * dozen documents, so a `/search` round-trip per character would be slower than a
 * local `includes`, and this is a "which of my known documents" choice, not a
 * semantic search.
 *
 * **"Your evidence library is empty" is only ever said about a library that was
 * actually read.** While the dialog is closed the fetcher resolves to `[]` rather
 * than calling the API, which means `data` is an empty array — not `null` — from
 * the very first render. Branching on `data === null` to decide "still loading" or
 * "the read failed", as this file used to, therefore never fired: a request that
 * was still in flight, and a request that had failed outright, both fell through
 * to the empty-state sentence and told the reader their library had nothing in it.
 * That is the same lie the library's "Indexing failed" badge used to tell, and it
 * is worse here, because the reader's next move is to go and re-upload documents
 * they already have. The branches below key off `status` instead, and the empty
 * sentence is the last resort rather than the fallback.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { CATEGORY_LABELS } from '@/models/documents'
import type { LibraryDocument } from '@/models/documents'
import { listDocuments } from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { ActionButton } from '@/components/ui/ActionButton'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { FileGlyph } from '@/components/documents/FileGlyph'
import { SearchIcon } from '@/components/ui/icons'

type ReassignDialogProps = {
  open: boolean
  /** The requirement being answered — shown so the reviewer keeps the clause in view. */
  requirementLabel: string
  /** The document currently on the match, so it can be marked and not re-picked. */
  currentDocumentId: string | null
  busy: boolean
  onCancel: () => void
  onSelect: (documentId: string) => void
}

export function ReassignDialog({
  open,
  requirementLabel,
  currentDocumentId,
  busy,
  onCancel,
  onSelect,
}: ReassignDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [term, setTerm] = useState('')

  /* Only read the library while the dialog is actually open — an unopened dialog
     should not fire a request on every parent render. The `open` flag is the dep. */
  const docs = useAsyncData(
    (signal) => (open ? listDocuments({}, { signal }) : Promise.resolve<LibraryDocument[]>([])),
    [open],
  )

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return

    if (open && !dialog.open) {
      dialog.showModal()
      setTerm('')
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  /* `isRefreshing` counts as loading here: the closed-dialog sentinel means the
     hook already holds a (empty) result when the dialog opens, so the real read is
     always a refresh rather than a first load. Without this the list would flash
     the empty state for the length of the request. */
  const loading = docs.status === 'loading' || docs.isRefreshing

  const rows = useMemo(() => {
    const all = docs.data ?? []
    const needle = term.trim().toLowerCase()
    if (!needle) return all
    return all.filter((doc) =>
      `${doc.title} ${doc.original_filename}`.toLowerCase().includes(needle),
    )
  }, [docs.data, term])

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault()
        onCancel()
      }}
      aria-labelledby="reassign-dialog-title"
      /*
       * `open:flex open:flex-col` rather than a bare `flex flex-col`: an author
       * `display` rule applies whether or not the `[open]` attribute is present, so
       * an unconditional `flex` here would out-rank the browser's own
       * `dialog:not([open]) { display: none }` and leave the box on screen forever,
       * Cancel or Escape having quietly cleared `open` underneath it. Gating the
       * display utility on the same attribute the browser already keys off of is
       * what makes `dialog.close()` (called from the effect below) actually make
       * this disappear, instead of just detaching focus and the ::backdrop while a
       * plain, non-modal box keeps rendering.
       */
      className={[
        'm-auto open:flex max-h-[min(32rem,calc(100vh-3rem))] w-[calc(100%-2rem)] max-w-lg open:flex-col',
        'rounded-2xl border border-hairline bg-surface p-0 shadow-panel backdrop:bg-ink-950/40',
      ].join(' ')}
    >
      <div className="border-b border-hairline px-5 py-4">
        <h2
          id="reassign-dialog-title"
          className="font-display text-base font-semibold tracking-tight text-neutral-900"
        >
          Reassign evidence
        </h2>
        <p className="mt-1 line-clamp-2 text-xs text-neutral-500">
          Choose the document that answers: {requirementLabel}
        </p>

        <label className="relative mt-3 block">
          <span className="sr-only">Search the evidence library</span>
          <SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-neutral-400" />
          <input
            type="search"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Search your library by name…"
            className={[
              'h-10 w-full rounded-xl border border-hairline bg-surface pr-3 pl-9 text-sm text-neutral-900',
              'placeholder:text-neutral-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-200 focus:outline-none',
            ].join(' ')}
          />
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {docs.status === 'error' ? (
          /* Shown whatever `data` holds. A failed read with a stale empty array
             behind it is still a failed read, and saying so with a Retry is the
             only honest thing on screen. */
          <ErrorBlock
            title="The library could not be read"
            message={docs.error ?? 'The request did not complete.'}
            offline={docs.offline}
            onRetry={docs.refetch}
          />
        ) : loading ? (
          <LoadingRows rows={4} label="Loading the evidence library" />
        ) : rows.length === 0 ? (
          <p className="px-5 py-10 text-center text-sm text-neutral-500">
            {term.trim()
              ? 'No document matches that name.'
              : 'Your evidence library is empty. Add documents from the Documents section first.'}
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-hairline">
            {rows.map((doc) => {
              const isCurrent = doc.id === currentDocumentId
              return (
                <li key={doc.id}>
                  <button
                    type="button"
                    disabled={isCurrent || busy}
                    onClick={() => onSelect(doc.id)}
                    className={[
                      'flex w-full items-start gap-3 px-5 py-3 text-left transition-colors duration-150',
                      isCurrent
                        ? 'cursor-default bg-surface-muted'
                        : 'hover:bg-selected disabled:pointer-events-none disabled:opacity-60',
                    ].join(' ')}
                  >
                    <FileGlyph filename={doc.original_filename} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-neutral-900">
                        {doc.title || doc.original_filename}
                      </span>
                      <span className="mt-0.5 block text-xs text-neutral-500">
                        {CATEGORY_LABELS[doc.category]}
                        {isCurrent ? ' · currently attached' : ''}
                      </span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t border-hairline px-5 py-4">
        <ActionButton variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </ActionButton>
      </div>
    </dialog>
  )
}
