/**
 * Watches one tender's analysis pipeline, live.
 *
 * A sibling of `useJobProgress` (the library indexer), and deliberately not the
 * same hook: the two sockets speak different frames and end on different rules,
 * and folding them together would mean a union type that is wrong half the time.
 * What is shared is the *shape* of the solution — a socket with a polling
 * fallback, a remembered failure point, and a seed that renders before anything
 * connects — so the structure below will read as familiar.
 *
 * Three things this socket does differently from the library's, all handled here:
 *
 *  1. **It needs the access token.** A browser cannot put an Authorization header
 *     on a `WebSocket`, so the token rides in the query string (see
 *     `tenderProgressUrl`). It is read from the auth store once, at connect time,
 *     not subscribed to — a token refresh mid-run must not tear the socket down
 *     and rebuild it, and the server only checks the token when the connection
 *     opens.
 *  2. **`ready_for_review` is not the end.** The pipeline pauses there for a human,
 *     but the socket stays open — the true terminal states are `finalized` and
 *     `failed` (`isSocketTerminal`). So a live socket sitting at `ready_for_review`
 *     stays `live`, waiting for the finalize frame; it is settled, not closed.
 *  3. **No ping, no `replayed` flag.** The tender socket does not send keepalive
 *     pings and does not tag its opening snapshot — it simply sends the latest
 *     persisted progress the instant it connects, then closes if that was already
 *     terminal. So a page opened after a run finished still renders the finished
 *     state rather than waiting for an event that will never come, exactly as the
 *     library's `replayed` snapshot achieves by a different means.
 *
 * Like the library hook it also tracks something the API does not store on the
 * row: **which stage a run died on**. A failed tender's status is `failed` and the
 * step it was on is gone; the stream is the only place that knew, so the last real
 * pipeline stage seen is remembered and handed to `stageStates`, which is what
 * puts the failure mark on the right node instead of failing the whole rail.
 *
 * `initialProgress` seeds the state before any connection is attempted — normally
 * `progressFromDetail(tender)` from the detail the processing page already
 * fetched. That is what lets the page render something honest with the backend
 * unreachable: it shows what it was handed, reports `offline`, and upgrades itself
 * the moment the socket or a poll succeeds.
 */

import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { getTender, tenderProgressUrl } from '@/services/tenderService'
import {
  IN_FLIGHT_STATUSES,
  PIPELINE_STAGES,
  STAGE_LABELS,
  TENDER_STATUS_LABELS,
  isSettled,
  isSocketTerminal,
  progressFromDetail,
  progressFromFrame,
} from '@/models/tenders'
import type { PipelineStage, TenderProgress, TenderProgressFrame, TenderStatus } from '@/models/tenders'

/**
 * `idle` before a tender is chosen, `live` on an open socket, `polling` after it
 * fell back to the REST endpoint, `offline` when neither works, `closed` once the
 * run has settled and there is nothing left to watch. `closed` is not a failure —
 * it is the normal end, and reads differently on screen from `offline`.
 */
export type TenderConnection = 'idle' | 'live' | 'polling' | 'offline' | 'closed'

const POLL_INTERVAL_MS = 2000

/**
 * The statuses that are a *step in progress* rather than a resting point, for
 * `failedAt` attribution. Exactly `IN_FLIGHT_STATUSES` — `ready_for_review` is a
 * pause, not a step, so a failure is never pinned to it.
 */
const REAL_STAGES: readonly TenderStatus[] = IN_FLIGHT_STATUSES

type UseTenderProgressOptions = {
  /** Rendered until a connection produces something. Usually `progressFromDetail(tender)`. */
  initialProgress?: TenderProgress
  /** A known failure point, for a tender that failed before this page was opened. */
  initialFailedAt?: PipelineStage
}

export function useTenderProgress(
  tenderId: string | null,
  options: UseTenderProgressOptions = {},
) {
  const [progress, setProgress] = useState<TenderProgress | null>(options.initialProgress ?? null)
  const [failedAt, setFailedAt] = useState<PipelineStage | undefined>(options.initialFailedAt)
  const [connection, setConnection] = useState<TenderConnection>('idle')

  /*
   * The seed is read inside the effect but must not be a dependency of it: it is a
   * fresh object on every render of the parent, so depending on it would tear the
   * socket down and rebuild it on every keystroke elsewhere on the page. A ref is
   * the standard way to read a current value from an effect that should not re-run
   * when it changes.
   */
  const seedRef = useRef(options)
  seedRef.current = options

  useEffect(() => {
    if (!tenderId) {
      setProgress(null)
      setFailedAt(undefined)
      setConnection('idle')
      return
    }

    /* Reset to the seed for the *new* tender, so switching tenders never shows the
       previous one's progress until the first frame arrives. */
    setProgress(seedRef.current.initialProgress ?? null)
    setFailedAt(seedRef.current.initialFailedAt)
    setConnection('idle')

    let cancelled = false
    let socket: WebSocket | null = null
    let pollTimer: number | null = null
    const controller = new AbortController()

    /** The last status that was a running step, so a later failure can be attributed. */
    let lastRealStage: PipelineStage | undefined = seedRef.current.initialFailedAt

    /** Set once the run reaches a socket-terminal state, so a close reads as sign-off. */
    let terminalSeen = false

    function record(status: TenderStatus, next: TenderProgress) {
      if (cancelled) {
        return
      }

      if ((REAL_STAGES as readonly string[]).includes(status)) {
        lastRealStage = status as PipelineStage
      }

      setProgress(next)

      if (status === 'failed') {
        setFailedAt(lastRealStage)
      }

      if (isSocketTerminal(status)) {
        terminalSeen = true
      }
    }

    function stopPolling() {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    }

    function startPolling() {
      if (cancelled || terminalSeen || pollTimer !== null) {
        return
      }

      setConnection('polling')

      let consecutiveFailures = 0

      const tick = async () => {
        try {
          // tenderId is non-null here: the effect returns early when it is null. The
          // guard's narrowing is lost across this nested async closure, hence the assert.
          const tender = await getTender(tenderId!, { signal: controller.signal })
          consecutiveFailures = 0
          record(tender.status, progressFromDetail(tender))

          /* Stop once the pipeline is no longer advancing on its own. At
             `ready_for_review` there is nothing more to poll for — the run pauses
             for the reviewer, and finalizing is a user action that returns the
             fresh row directly — so settling, not just socket-terminal, ends the
             poll. */
          if (isSettled(tender.status)) {
            stopPolling()
            if (!cancelled) {
              setConnection('closed')
            }
          }
        } catch {
          if (cancelled) {
            return
          }

          consecutiveFailures += 1
          setConnection('offline')

          /* Three strikes and it stops. One failed poll is a service restarting and
             worth waiting out; twenty is no backend running, and hammering a dead
             port every two seconds for the life of the tab buys nothing. The page
             offers a Retry, which remounts this hook. */
          if (consecutiveFailures >= 3) {
            stopPolling()
          }
        }
      }

      void tick()
      pollTimer = window.setInterval(() => void tick(), POLL_INTERVAL_MS)
    }

    /* Read the token once, here, rather than subscribing to it: the server only
       validates it at connect, and a refresh must not remount the socket. When it
       is null the connection will be refused and onerror drops us straight to
       polling, which goes through apiClient and refreshes on its own. */
    const token = useAuthStore.getState().accessToken

    try {
      socket = new WebSocket(tenderProgressUrl(tenderId, token))
    } catch {
      /* A malformed URL throws synchronously rather than firing onerror. */
      startPolling()
      return () => {
        cancelled = true
        controller.abort()
        stopPolling()
      }
    }

    socket.onopen = () => {
      if (!cancelled) {
        setConnection('live')
      }
    }

    socket.onmessage = (event) => {
      let payload: unknown

      try {
        payload = JSON.parse(String(event.data))
      } catch {
        /* Not JSON. Nothing sensible to do, and throwing here would kill the socket
           over a stray frame. */
        return
      }

      if (typeof payload !== 'object' || payload === null) {
        return
      }

      const frame = payload as Partial<TenderProgressFrame> & { error?: string }

      if (frame.error) {
        /* The server telling us its own pub/sub is down. The socket is about to
           close; polling reads straight from Postgres and still works. (The tender
           socket does not send keepalive pings, so there is no ping frame to filter
           out the way the library socket needs.) */
        socket?.close()
        startPolling()
        return
      }

      if (!frame.status || !frame.tender_id) {
        return
      }

      /* Fill the frame out to the full shape `progressFromFrame` expects. The
         contract guarantees every field, but a step label derived from the status
         is a safe fallback that keeps the status line from going blank, and the
         client's clock is the only honest timestamp when the frame omits one. */
      const status = frame.status
      record(
        status,
        progressFromFrame({
          tender_id: frame.tender_id,
          status,
          step_label:
            frame.step_label ||
            STAGE_LABELS[status as PipelineStage] ||
            TENDER_STATUS_LABELS[status],
          current_step: frame.current_step ?? 0,
          total_steps: frame.total_steps ?? PIPELINE_STAGES.length,
          percent_complete: frame.percent_complete ?? 0,
          message: frame.message ?? null,
          extracted_requirements_count: frame.extracted_requirements_count ?? null,
          updated_at: frame.updated_at ?? new Date().toISOString(),
        }),
      )

      if (isSocketTerminal(status)) {
        setConnection('closed')
      }
    }

    socket.onerror = () => {
      /* Fires before onclose when the handshake fails — no backend, wrong port, a
         rejected token, a proxy that will not upgrade. All of them mean: stop
         waiting, start polling. */
      startPolling()
    }

    socket.onclose = () => {
      if (cancelled) {
        return
      }

      /* A close after a socket-terminal state is the server signing off. Any other
         close is a connection we still need, so fall back rather than go quiet.

         The check is a plain variable, not a `setConnection` updater: an updater
         must be pure, and React invokes it twice under StrictMode — starting a poll
         from inside one would leave a second interval running with no handle to
         clear it. */
      if (terminalSeen) {
        setConnection('closed')
        return
      }

      startPolling()
    }

    return () => {
      cancelled = true
      controller.abort()
      stopPolling()

      if (socket) {
        /* Drop the handlers before closing: onclose fires during teardown and would
           otherwise restart polling on a hook that is going away. */
        socket.onopen = null
        socket.onmessage = null
        socket.onerror = null
        socket.onclose = null
        socket.close()
      }
    }
  }, [tenderId])

  return { progress, failedAt, connection }
}
