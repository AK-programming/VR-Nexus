/**
 * The two states every live screen has and no mock ever needs.
 *
 * The Documents pages used to render fixtures, so they had exactly one state: data. A
 * page that talks to a real service has three, and the two extra ones are where a UI
 * either earns trust or loses it. They live here rather than in each page because three
 * pages inventing three skeletons is how a section starts to feel assembled from parts.
 *
 * The rule these follow: never show a spinner where the shape of the answer is already
 * known. A table is about to appear, so the skeleton is table-shaped rows; the eye
 * settles in the right place before the data lands and nothing jumps when it does. A
 * bare centred spinner throws that away and makes every wait feel identical.
 */

import type { ReactNode } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertTriangleIcon, SignalOffIcon } from '@/components/ui/icons'

/**
 * Row-shaped placeholders for a list or table that is loading.
 *
 * `rows` should match roughly what the container usually holds. Too few and the panel
 * visibly grows when data arrives; too many and an empty library flashes a tall grey
 * block before collapsing to an empty state.
 *
 * `aria-hidden` with a live region alongside it, rather than labelling the bars
 * themselves: a screen reader should hear "Loading documents" once, not a description
 * of eight decorative rectangles.
 */
export function LoadingRows({ rows = 5, label }: { rows?: number; label: string }) {
  return (
    /* relative: the sr-only status line below needs a containing block of its
       own, or it anchors against the document root and can escape every
       overflow clip between here and <html> while a page is loading. */
    <div className="relative px-5 py-4">
      <p role="status" className="sr-only">
        {label}
      </p>
      <div aria-hidden="true" className="flex flex-col gap-3">
        {Array.from({ length: rows }, (_, index) => (
          <div key={index} className="flex items-center gap-3">
            <div className="size-9 shrink-0 animate-pulse rounded-xl bg-surface-muted motion-reduce:animate-none" />
            <div className="min-w-0 flex-1">
              {/*
                Two bars of unequal width, and the widths vary per row. Uniform bars read
                as a loading *graphic*; ragged ones read as text that has not arrived,
                which is what is actually happening. The widths are derived from the index
                rather than random so nothing reflows between renders.
              */}
              <div
                className="h-3.5 animate-pulse rounded-md bg-surface-muted motion-reduce:animate-none"
                style={{ width: `${52 + ((index * 13) % 34)}%` }}
              />
              <div
                className="mt-2 h-2.5 animate-pulse rounded-md bg-surface-muted motion-reduce:animate-none"
                style={{ width: `${28 + ((index * 7) % 18)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * A read that failed, with the one control that can fix it.
 *
 * The offline case gets its own glyph and its own sentence because it has a different
 * cause and a different fix: nothing is wrong with the request, the service is not
 * answering. `ApiError.isOffline` is set when fetch itself rejected, and telling the
 * two apart is the difference between "start the backend" and "this document is gone".
 *
 * The message from the API is shown verbatim underneath rather than replaced with
 * something friendlier. It is written by the service for a person — "This exact file is
 * already in the library", "Document not found" — and paraphrasing it loses the only
 * specific detail on screen.
 */
export function ErrorBlock({
  title,
  message,
  offline = false,
  onRetry,
}: {
  title: string
  message: string
  offline?: boolean
  onRetry?: () => void
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <span
        aria-hidden="true"
        className={`flex size-11 items-center justify-center rounded-2xl ${
          offline ? 'bg-surface-muted text-neutral-500' : 'bg-rose-50 text-rose-600'
        }`}
      >
        {offline ? <SignalOffIcon className="size-5" /> : <AlertTriangleIcon className="size-5" />}
      </span>

      <div className="max-w-md">
        <p className="font-display text-base font-semibold text-neutral-900">{title}</p>
        <p className="mt-1 text-sm text-neutral-600">{message}</p>
        {offline ? (
          <p className="mt-2 text-xs text-neutral-500">
            The Evidence Library API should be running on port 8000.
          </p>
        ) : null}
      </div>

      {onRetry ? (
        <ActionButton variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </ActionButton>
      ) : null}
    </div>
  )
}

/**
 * A quiet inline banner for a refresh that failed over data still on screen.
 *
 * Distinct from `ErrorBlock` on purpose: the rows below are still readable and still
 * true as of a minute ago, so replacing them with an error would destroy something
 * useful to report something minor. This says the last refresh did not land and leaves
 * the reader in charge of what to do about it.
 */
export function StaleDataNotice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col gap-2 border-b border-hairline bg-surface-muted px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
      <p className="flex items-start gap-2 text-sm text-neutral-700">
        <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-neutral-500" />
        <span>
          Showing the last successful read. {message}
        </span>
      </p>
      <ActionButton variant="secondary" size="sm" onClick={onRetry}>
        Retry
      </ActionButton>
    </div>
  )
}

/**
 * Wraps a panel body so the three states are resolved in one place.
 *
 * Deliberately not a generic render-prop component over the hook's whole return value.
 * Each page needs slightly different copy and a different empty state, and a component
 * that tried to own all of that would grow a prop for every difference. This just
 * settles the ordering — error-with-no-data wins over loading, loading wins over
 * content — which is the part that is easy to get subtly wrong by hand.
 */
export function AsyncSection({
  status,
  hasData,
  loading,
  error,
  children,
}: {
  status: 'loading' | 'success' | 'error'
  hasData: boolean
  loading: ReactNode
  error: ReactNode
  children: ReactNode
}) {
  if (status === 'error' && !hasData) {
    return <>{error}</>
  }

  if (status === 'loading' && !hasData) {
    return <>{loading}</>
  }

  return <>{children}</>
}
