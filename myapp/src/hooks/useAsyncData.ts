/**
 * One read, fetched on mount, with the four states a screen actually has to draw.
 *
 * Every Documents screen needs the same four things — a skeleton while the first
 * request is out, an error with a way to try again, an empty state, and the data — and
 * writing that by hand in each page is how three pages end up with three different
 * ideas of what "loading" looks like. So the shape lives here once and the pages
 * render it.
 *
 * Three decisions in here are load-bearing:
 *
 *   **Cancellation.** Every run gets an `AbortController` and the cleanup aborts it.
 *   The old harness had none, and it shows: switching category twice quickly could let
 *   the first response land after the second and overwrite it, because both did an
 *   unconditional `container.innerHTML = …`. Aborting means the stale response never
 *   resolves at all, which is a stronger guarantee than checking a flag afterwards. It
 *   is also what keeps React's StrictMode double-mount from firing two live requests.
 *
 *   **A refetch does not blank the screen.** After a delete or a retrain the page wants
 *   fresh data, but dropping back to a skeleton makes a 200ms request look like a page
 *   reload. So `data` is kept and `isRefreshing` is raised instead, and the pages show
 *   that as a quiet indicator on the refresh control rather than as a full redraw.
 *
 *   **An error keeps the last good data.** A failed refresh should not throw away rows
 *   that are still perfectly readable. `status` goes to `error` and `data` stays, so a
 *   page can decide: no data means the full-page error state, data present means an
 *   inline banner over a list that still works.
 *
 * `deps` is an explicit array for the same reason `useEffect` takes one. The fetcher is
 * an inline arrow at every call site and so is a new function on every render; making
 * it a dependency would refetch forever. It is read through a ref, and the caller
 * declares what actually changes the request.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, errorMessage } from '@/lib/apiClient'

export type AsyncStatus = 'loading' | 'success' | 'error'

export type AsyncData<T> = {
  status: AsyncStatus
  /** Kept across a refetch and across a failed refetch. Null only before the first success. */
  data: T | null
  error: string | null
  /**
   * True when the request never reached the server, rather than reaching it and being
   * refused. The distinction is the whole difference between "start the API" and "this
   * document is gone", so it is resolved here — where `ApiError` is already in scope —
   * instead of leaving each page to sniff the message text for it.
   */
  offline: boolean
  /**
   * True when the server answered 404. A detail screen has to tell "this id does not
   * exist" from "the read failed" — the first is a dead end that should offer a way back
   * to the list, the second is worth a Try again — and the status code is the only
   * honest way to know which. Resolved here for the same reason as `offline`.
   */
  notFound: boolean
  /** True while a refetch is in flight over data that is already on screen. */
  isRefreshing: boolean
  /** Re-runs the fetcher. Safe to pass straight to onClick. */
  refetch: () => void
}

type State<T> = {
  status: AsyncStatus
  data: T | null
  error: string | null
  offline: boolean
  notFound: boolean
  isRefreshing: boolean
}

/** True for the DOMException a cancelled fetch throws, which is not a failure to report. */
function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function useAsyncData<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
): AsyncData<T> {
  const [state, setState] = useState<State<T>>({
    status: 'loading',
    data: null,
    error: null,
    offline: false,
    notFound: false,
    isRefreshing: false,
  })

  /*
   * Read inside the effect, deliberately not a dependency of it. See the header.
   */
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  /*
   * Bumping this re-runs the effect, which is the whole of `refetch`. A counter rather
   * than calling the fetcher directly, so a manual refresh goes through exactly the
   * same code path as the initial load — including cancellation of whatever the
   * previous run had in flight.
   */
  const [reloadToken, setReloadToken] = useState(0)

  const refetch = useCallback(() => {
    setReloadToken((token) => token + 1)
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    setState((previous) =>
      previous.data === null
        ? {
            status: 'loading',
            data: null,
            error: null,
            offline: false,
            notFound: false,
            isRefreshing: false,
          }
        : {
            ...previous,
            status: 'success',
            error: null,
            offline: false,
            notFound: false,
            isRefreshing: true,
          },
    )

    fetcherRef
      .current(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) {
          return
        }
        setState({
          status: 'success',
          data,
          error: null,
          offline: false,
          notFound: false,
          isRefreshing: false,
        })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isAbort(error)) {
          return
        }
        setState((previous) => ({
          status: 'error',
          data: previous.data,
          error: errorMessage(error),
          offline: error instanceof ApiError && error.isOffline,
          notFound: error instanceof ApiError && error.status === 404,
          isRefreshing: false,
        }))
      })

    return () => {
      controller.abort()
    }
    // The caller owns this list; spreading it is the point of the hook.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadToken])

  return {
    status: state.status,
    data: state.data,
    error: state.error,
    offline: state.offline,
    notFound: state.notFound,
    isRefreshing: state.isRefreshing,
    refetch,
  }
}
