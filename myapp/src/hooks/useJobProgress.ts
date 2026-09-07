/**
 * Watches one indexing job, live.
 *
 * This is `VR_Project/frontend/js/app.js`'s socket handling, ported. The harness got
 * three things right that are easy to leave out, and all three are here:
 *
 *  1. **The replayed snapshot.** On connect the server sends the job's persisted row
 *     flagged `replayed`, then closes immediately if the job already finished. So a
 *     page opened after a job completed still renders the finished state instead of
 *     waiting forever for an event that will never come.
 *  2. **Idle pings.** `{"type":"ping"}` arrives on a quiet connection to keep proxies
 *     from dropping it. Parsed as a progress event it would set `stage` to undefined
 *     and blank the timeline, so it is filtered before anything reads it.
 *  3. **The polling fallback.** If Redis is unreachable the server sends `{"error":…}`
 *     and closes; a proxy or a dropped network closes without saying anything. Either
 *     way the answer is the same — poll `GET /jobs/{id}` every two seconds, which the
 *     backend supports precisely so a socket is never load-bearing.
 *  4. **A ticket, not a bare connection.** This socket used to accept any connection
 *     with no credential at all. It now requires a short-lived, single-use ticket
 *     minted over an ordinary authenticated POST (`mintJobWsTicket`) right before the
 *     socket opens - the same shape the tender progress socket already used, see
 *     `jobProgressUrl`.
 *
 * It also tracks something the API does not store: **which stage a job died on**. A
 * failed job's `stage` is `failed`, and the step it was running is gone. Watching the
 * stream is the only way to know, so the last real stage seen is remembered and handed
 * to `stageStates`, which is what puts the mark on the right node rather than guessing.
 *
 * `initialJob` seeds the state before any connection is attempted. That is what makes
 * the page useful with no backend running: it renders what it was given, reports
 * `offline`, and upgrades itself the moment the service is reachable. No simulated
 * progress, no separate mock code path.
 */

import { useEffect, useRef, useState } from 'react'
import { getJob, jobProgressUrl, mintJobWsTicket } from '@/services/documentService'
import { isTerminalStage } from '@/models/documents'
import type { IndexJob, ProgressEvent, TimelineStage } from '@/models/documents'

/**
 * `idle` before a job is chosen, `live` on an open socket, `polling` after it fell
 * back, `offline` when neither works, `closed` once the job is terminal and the server
 * hung up — which is success, not a problem, and reads differently on screen.
 */
export type JobConnection = 'idle' | 'live' | 'polling' | 'offline' | 'closed'

const POLL_INTERVAL_MS = 2000

/** The stages that are a step rather than an end state, for `failedAt` tracking. */
const REAL_STAGES: readonly TimelineStage[] = ['queued', 'parsing', 'tagging', 'embedding']

type UseJobProgressOptions = {
  /** Rendered until a connection produces something. Usually the row already on screen. */
  initialJob?: IndexJob
  /** A known failure point, for a job that failed before this page was opened. */
  initialFailedAt?: TimelineStage
}

export function useJobProgress(jobId: string | null, options: UseJobProgressOptions = {}) {
  const [job, setJob] = useState<IndexJob | null>(options.initialJob ?? null)
  const [failedAt, setFailedAt] = useState<TimelineStage | undefined>(options.initialFailedAt)
  const [connection, setConnection] = useState<JobConnection>('idle')

  /*
   * The seed is read inside the effect but must not be a dependency of it: it is a
   * fresh object on every render of the parent, so depending on it would tear the
   * socket down and rebuild it sixty times a second. A ref is the standard way to
   * read a current value from an effect that should not re-run when it changes.
   */
  const seedRef = useRef(options)
  seedRef.current = options

  useEffect(() => {
    if (!jobId) {
      setJob(null)
      setFailedAt(undefined)
      setConnection('idle')
      return
    }

    /* Reset to the seed for the *new* job. Without this, switching jobs would show
       the previous job's progress until the first event arrived. */
    setJob(seedRef.current.initialJob ?? null)
    setFailedAt(seedRef.current.initialFailedAt)
    setConnection('idle')

    let cancelled = false
    let socket: WebSocket | null = null
    let pollTimer: number | null = null
    const controller = new AbortController()

    /** The last stage that was a step, so a later failure can be attributed to it. */
    let lastRealStage: TimelineStage | undefined = seedRef.current.initialFailedAt

    /** Set once the job reports `complete` or `failed`, so a close reads as sign-off. */
    let terminalSeen = false

    function record(stage: IndexJob['stage'], next: IndexJob) {
      if (cancelled) {
        return
      }

      if ((REAL_STAGES as readonly string[]).includes(stage)) {
        lastRealStage = stage as TimelineStage
      }

      setJob(next)

      if (stage === 'failed') {
        setFailedAt(lastRealStage)
      }

      if (isTerminalStage(stage)) {
        terminalSeen = true
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
          // jobId is non-null here: the effect returns early when it is null; the
          // guard's narrowing does not reach into this nested async closure.
          const next = await getJob(jobId!, { signal: controller.signal })
          consecutiveFailures = 0
          record(next.stage, next)

          if (isTerminalStage(next.stage)) {
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

          /* Three strikes and it stops. A single failed poll is a service restarting
             and worth waiting out; twenty of them is no backend running, and hammering
             a dead port every two seconds for the life of the tab buys nothing. The
             page offers a Retry, which remounts this hook. */
          if (consecutiveFailures >= 3) {
            stopPolling()
          }
        }
      }

      void tick()
      pollTimer = window.setInterval(() => void tick(), POLL_INTERVAL_MS)
    }

    function stopPolling() {
      if (pollTimer !== null) {
        window.clearInterval(pollTimer)
        pollTimer = null
      }
    }

    /* Wiring the socket's event handlers is pulled out into its own function so
       both the normal path and the "ticket mint failed" path below can bail out
       through the exact same startPolling() without duplicating the handler
       bodies. */
    function attachHandlers(ws: WebSocket) {
      ws.onopen = () => {
        if (!cancelled) {
          setConnection('live')
        }
      }

      ws.onmessage = (event) => {
        let payload: unknown

        try {
          payload = JSON.parse(String(event.data))
        } catch {
          /* Not JSON. Nothing sensible to do with it, and throwing here would kill the
             socket over a stray frame. */
          return
        }

        if (typeof payload !== 'object' || payload === null) {
          return
        }

        const frame = payload as Partial<ProgressEvent> & { type?: string; error?: string }

        if (frame.type === 'ping') {
          return
        }

        if (frame.error) {
          /* The server telling us its own pub/sub is down. The socket is about to close;
             polling reads straight from Postgres and still works. */
          ws.close()
          startPolling()
          return
        }

        if (!frame.stage || !frame.job_id) {
          return
        }

        record(frame.stage, {
          id: frame.job_id,
          document_id: frame.document_id ?? '',
          stage: frame.stage,
          progress: frame.progress ?? 0,
          /* `''`, not `null`. `index_jobs.message` is `nullable=False, default=""` and
             `JobOut.message` is a plain `str`, so the field is never null on the wire and
             `IndexJob.message` is typed `string` to match. A `null` here would not just be
             a lie about the contract, it would fail the build. */
          message: frame.message ?? '',
          /* The socket frame carries no timestamp. This is the moment the client saw the
             event, which is close enough for a relative "updated 3s ago" and is the only
             honest value available — the row's real `updated_at` arrives with the next
             poll or refetch. */
          updated_at: new Date().toISOString(),
        })

        if (isTerminalStage(frame.stage)) {
          setConnection('closed')
        }
      }

      ws.onerror = () => {
        /* Fires before onclose when the handshake fails - no backend, wrong port, a
           rejected or already-redeemed ticket, a proxy that will not upgrade. All of
           them mean: stop waiting, start polling. */
        startPolling()
      }

      ws.onclose = () => {
        if (cancelled) {
          return
        }

        /* A close after a terminal stage is the server signing off politely. Any other
           close is a connection we still need, so fall back rather than go quiet.

           The check is a plain variable, not a `setConnection` updater: an updater must
           be pure, and React invokes it twice under StrictMode — starting a poll from
           inside one would leave a second interval running with no handle to clear it. */
        if (terminalSeen) {
          setConnection('closed')
          return
        }

        startPolling()
      }
    }

    /* Opening the socket now needs an HTTP round trip first (minting the ticket),
       so the whole thing is async - unlike before, when `new WebSocket(...)` could
       happen synchronously inside the effect. `cancelled` is checked again right
       after the mint resolves: if the effect was cleaned up while that request was
       in flight (jobId changed, the component unmounted), the ticket is simply left
       to expire unused (it is single-use and dies in 60s on its own) rather than
       opening a socket nothing will ever close. */
    async function connect() {
      let ticket: string
      try {
        ticket = await mintJobWsTicket(jobId!, { signal: controller.signal })
      } catch {
        if (!cancelled) {
          startPolling()
        }
        return
      }

      if (cancelled) {
        return
      }

      try {
        socket = new WebSocket(jobProgressUrl(jobId!, ticket))
      } catch {
        /* A malformed URL throws synchronously rather than firing onerror. */
        startPolling()
        return
      }

      attachHandlers(socket)
    }

    void connect()

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
  }, [jobId])

  return { job, failedAt, connection }
}
