/**
 * The single seam between this app and the VR-Nexus API.
 *
 * Nothing outside this file should call fetch(). Keeping one entry point means
 * auth headers, retries or request logging are added in one place later, and
 * every caller gets a consistent error object today.
 */

/**
 * Empty in development so requests stay relative and pass through the Vite proxy
 * defined in vite.config.ts. Trailing slashes are trimmed so joining a path can
 * never produce a double slash.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

/**
 * FastAPI reports failures in more than one shape, and callers should not have to
 * care which one arrived:
 *
 *   HTTPException(detail="...")            -> { detail: "..." }
 *   request validation (422)               -> { detail: [{ loc, msg, type }] }
 *   HTTPException(detail={...})             -> { detail: { message, ... } }
 *
 * `message` is always a string worth showing a user; `detail` keeps the original
 * payload for the cases where a caller needs the structured version.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown
  /** True when the request never reached the server — server down, DNS, offline. */
  readonly isOffline: boolean

  constructor(message: string, status: number, detail: unknown, isOffline = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.isOffline = isOffline
  }
}

type ValidationIssue = {
  loc?: unknown[]
  msg?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Pulls a human-readable sentence out of any of the three shapes above. */
function readMessage(body: unknown, status: number): string {
  const detail = isRecord(body) ? body.detail : body

  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  if (Array.isArray(detail)) {
    const parts = (detail as ValidationIssue[])
      .map((issue) => {
        // loc is like ["body", "title"] — the last entry is the field name.
        const field = Array.isArray(issue.loc) ? issue.loc.at(-1) : undefined
        const text = issue.msg ?? 'is invalid'
        return field ? `${String(field)}: ${text}` : text
      })
      .filter(Boolean)

    if (parts.length) {
      return parts.join('; ')
    }
  }

  if (isRecord(detail) && typeof detail.message === 'string' && detail.message.trim()) {
    return detail.message
  }

  return `Request failed with status ${status}.`
}

/**
 * Where the access token comes from.
 *
 * The client cannot import the store — the store imports the services, which
 * import this file, and the cycle would be real rather than cosmetic. So the
 * store pushes a getter in instead, and every request picks up the current token
 * without any caller remembering to attach it. Reading through a function rather
 * than holding the string means a refresh or a sign-out takes effect on the next
 * request, not the next reload.
 */
let readAuthToken: () => string | null = () => null

export function setAuthTokenProvider(provider: () => string | null): void {
  readAuthToken = provider
}

/**
 * What to do about a 401.
 *
 * The same seam as the token provider, and for the same reason — this file cannot
 * import the store. The store registers something that trades the refresh token
 * for a fresh pair and reports whether it worked; `request` below then replays the
 * original call with the new token, so an expired access token is invisible to
 * every caller. Access tokens live 24 hours, which is exactly long enough for a
 * tab left open overnight to start failing silently without this.
 *
 * Left null, a 401 simply surfaces as an ApiError, so the client is usable
 * without the store wired up at all.
 */
let handleUnauthorized: (() => Promise<boolean>) | null = null

export function setUnauthorizedHandler(handler: () => Promise<boolean>): void {
  handleUnauthorized = handler
}

/**
 * One refresh at a time.
 *
 * When a token expires it usually expires for several in-flight requests at once.
 * Without this, each would start its own refresh: N identical round trips, and
 * because each returns a *different* valid token pair, whichever resolved last
 * would win and the tokens the others had already stored would be discarded — so
 * requests replayed with them fail for no visible reason. The first caller runs the
 * refresh; the rest await the same promise and act on its result.
 *
 * It also keeps this correct if the API ever starts invalidating a refresh token
 * once it has been exchanged, which is the usual next step for rotation. Today it
 * does not — tokens are validated by decoding alone — and concurrent refreshes
 * would merely be wasteful rather than destructive.
 */
let refreshInFlight: Promise<boolean> | null = null

function refreshOnce(): Promise<boolean> {
  if (!handleUnauthorized) {
    return Promise.resolve(false)
  }

  if (!refreshInFlight) {
    refreshInFlight = handleUnauthorized()
      // A handler that throws means the refresh failed; it must not become an
      // unhandled rejection in every request that happened to be waiting.
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null
      })
  }

  return refreshInFlight
}

type RequestOptions = {
  method?: string
  body?: BodyInit
  headers?: Record<string, string>
  signal?: AbortSignal
  /**
   * Set for the endpoints that must not carry a bearer token: sign-in, sign-up
   * and refresh. Sending a stale or expired access token to those is at best
   * noise and at worst a 401 on a request that should have succeeded.
   */
  anonymous?: boolean
  /**
   * How to read a successful response body. Defaults to JSON.
   *
   * `blob` exists for the two library routes that return bytes rather than JSON —
   * the PDF itself and each extracted image. Those cannot be fetched by handing a
   * bare URL to `<img src>` or to react-pdf, because a browser-initiated request
   * like that sends no Authorization header and every library route now requires
   * one. Going through this function instead means they get the bearer token, the
   * single-flight refresh and the retry that every other call already gets.
   *
   * Only the success path changes. A failure on a binary route still arrives as
   * JSON, so the error handling below reads text either way.
   */
  parse?: 'json' | 'blob'
}

/**
 * `isRetry` is set only by the 401 path below, and it is what makes the recursion
 * terminate: a replayed request never gets a second chance to refresh, so the
 * worst case is one refresh and one retry per call.
 */
async function request<T>(
  path: string,
  options: RequestOptions = {},
  isRetry = false,
): Promise<T> {
  let response: Response

  // Rebuilt on every attempt rather than reused, so a retry picks up the token
  // the refresh just wrote instead of replaying the expired one.
  const headers: Record<string, string> = { ...options.headers }

  if (!options.anonymous && !headers.Authorization) {
    const token = readAuthToken()
    if (token) {
      headers.Authorization = `Bearer ${token}`
    }
  }

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body,
      signal: options.signal,
    })
  } catch (error) {
    // An AbortError is the caller's own doing, so let it through untouched —
    // wrapping it would make cancelled requests look like real failures.
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }
    throw new ApiError('Could not reach the server. Is the API running?', 0, error, true)
  }

  // 204 No Content — DELETE returns this. There is no body to parse.
  if (response.status === 204) {
    return undefined as T
  }

  /**
   * Binary success. Read as a Blob only once the response is known to be good:
   * `response.body` can be consumed exactly once, so this has to be decided before
   * the text read below rather than after it.
   *
   * A failed binary request falls through to the JSON path on purpose. FastAPI
   * answers a 401, 403 or 404 on these routes with the same JSON envelope as any
   * other endpoint, so reading it as text produces the usual ApiError — including
   * the 401 refresh-and-retry, which replays with `parse` intact and so still
   * returns a Blob on the second attempt.
   */
  if (response.ok && options.parse === 'blob') {
    return (await response.blob()) as T
  }

  const raw = await response.text()
  let body: unknown = undefined

  if (raw) {
    try {
      body = JSON.parse(raw)
    } catch {
      // A non-JSON body means a proxy or crash page, not our API. Keep the text
      // so the error message is still informative.
      body = raw
    }
  }

  if (!response.ok) {
    /**
     * A 401 on an authenticated request almost always means the access token
     * expired rather than that the user is unwelcome, so try once to renew it and
     * replay the call. Three conditions keep this from misfiring:
     *
     *   anonymous  — sign-in, sign-up and refresh itself must never recurse here.
     *                A 401 from the login endpoint is a wrong password, and
     *                refreshing in response to it would be nonsense.
     *   isRetry    — the replay gets no second refresh, so this terminates.
     *   a handler  — without the store wired in there is nothing to refresh with.
     *
     * `options.body` is replayable because everything sent through `api` is a
     * string or FormData. A streaming body would already be consumed by now and
     * would need buffering before this could retry it.
     */
    if (response.status === 401 && !options.anonymous && !isRetry && handleUnauthorized) {
      if (await refreshOnce()) {
        return request<T>(path, options, true)
      }
    }

    throw new ApiError(readMessage(body, response.status), response.status, body)
  }

  return body as T
}

/**
 * Per-call knobs every method shares. Kept as one object rather than a trailing
 * positional `signal` so adding the next one (a timeout, say) is not a breaking
 * change at every call site.
 */
export type CallOptions = {
  signal?: AbortSignal
  /** Send without the Authorization header. See RequestOptions.anonymous. */
  anonymous?: boolean
}

export const api = {
  get: <T>(path: string, options: CallOptions = {}) => request<T>(path, options),

  /**
   * GET that resolves to the raw bytes, with the bearer token attached.
   *
   * For the endpoints that serve a file rather than JSON. The caller almost always
   * wants `URL.createObjectURL(blob)` next, and owns revoking it — see the
   * `fetch*ObjectUrl` helpers in documentService, which pair the two.
   *
   * One status code to know about: a request with no Authorization header at all is
   * rejected by FastAPI's HTTPBearer with **403**, not 401, so it does not trigger
   * the refresh above. That is the right behaviour — there is nothing to refresh
   * when nobody is signed in — but it means a 403 from one of these routes reads as
   * "no session", not "your role is insufficient".
   */
  getBlob: (path: string, options: CallOptions = {}) =>
    request<Blob>(path, { ...options, parse: 'blob' }),

  postJson: <T>(path: string, payload: unknown, options: CallOptions = {}) =>
    request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      ...options,
    }),

  /**
   * Multipart upload. Content-Type is intentionally omitted — the browser has to
   * set it so that it can append the multipart boundary. Setting it by hand is
   * the classic cause of a 422 on a file upload that looks perfectly correct.
   */
  postForm: <T>(path: string, formData: FormData, options: CallOptions = {}) =>
    request<T>(path, { method: 'POST', body: formData, ...options }),

  /** POST with no body, for endpoints that act purely on the URL. */
  postEmpty: <T>(path: string, options: CallOptions = {}) =>
    request<T>(path, { method: 'POST', ...options }),

  /**
   * Partial update. Like `postJson` but with the PATCH verb, for the tender
   * routes that edit one resource in place — metadata (`PATCH /tenders/{id}`)
   * and a single match review (`PATCH /tenders/{id}/matches/{id}`). The body is
   * a string, so it replays cleanly through the 401 refresh-and-retry above.
   */
  patchJson: <T>(path: string, payload: unknown, options: CallOptions = {}) =>
    request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      ...options,
    }),

  delete: <T = void>(path: string, options: CallOptions = {}) =>
    request<T>(path, { method: 'DELETE', ...options }),
}

/**
 * Absolute ws:// or wss:// URL for a WebSocket path. In development the Vite
 * proxy handles /ws, so this resolves against the dev server's own origin and
 * automatically picks wss when the page is served over https.
 */
export function websocketUrl(path: string): string {
  if (API_BASE_URL) {
    return `${API_BASE_URL.replace(/^http/, 'ws')}${path}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

/** Safe message for any thrown value, so UI never renders "[object Object]". */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Something went wrong.'
}
