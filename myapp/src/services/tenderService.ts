/**
 * Every call the Tender Analysis feature makes, in one module.
 *
 * Mirrors `documentService.ts` in structure — named functions rather than inline
 * fetches, an undefined-dropping query builder, and authenticated binary reads
 * that hand back object URLs — but talks to a different surface (`/api/tenders`)
 * with its own shapes. The two are deliberately kept apart, the same way the two
 * storage backends and the two progress sockets are on the server.
 *
 * Every route here is authenticated: `apiClient` attaches the bearer token to
 * everything it sends, so nothing in this file thinks about auth — except the
 * progress WebSocket, which a browser cannot put a header on. It authenticates
 * with a short-lived, single-use ticket instead of the access token itself
 * (see `mintTenderWsTicket` and `tenderProgressUrl`).
 *
 * Nothing here catches. `apiClient` already unwraps FastAPI's error shapes into
 * an `ApiError` with a readable `.message` and a `.status`; a caller that wants a
 * sentence calls `errorMessage`, and one that wants to branch on a 404 reads
 * `error.status`.
 */

import { api, websocketUrl, type CallOptions } from '@/lib/apiClient'
import type {
  EvaluationImpact,
  EvidenceMatch,
  MatchReviewUpdate,
  MatchType,
  MatchReviewStatus,
  Requirement,
  TenderDetail,
  TenderListItem,
  TenderReport,
  TenderStatus,
  TenderUpdate,
  TenderUploadResponse,
} from '@/models/tenders'

const BASE = '/api/tenders'

/* -------------------------------------------------------------------------- */
/* Reading                                                                    */
/* -------------------------------------------------------------------------- */

export type ListTendersQuery = {
  /** The wire parameter is `status` (aliased from `tender_status` on the server). */
  status?: TenderStatus
  /** Server bounds: 1-500, default 100. */
  limit?: number
  offset?: number
}

/**
 * `GET /api/tenders`, newest first.
 *
 * Undefined values are dropped rather than sent empty — `?status=` with no value
 * is a 422 from FastAPI's enum coercion, not an absent filter.
 */
export function listTenders(
  query: ListTendersQuery = {},
  options: CallOptions = {},
): Promise<TenderListItem[]> {
  const params = new URLSearchParams()

  if (query.status) {
    params.set('status', query.status)
  }
  if (query.limit !== undefined) {
    params.set('limit', String(query.limit))
  }
  if (query.offset !== undefined) {
    params.set('offset', String(query.offset))
  }

  const search = params.toString()
  return api.get<TenderListItem[]>(`${BASE}${search ? `?${search}` : ''}`, options)
}

/** `GET /api/tenders/{id}` — full detail, including the derived `has_output`. */
export function getTender(tenderId: string, options: CallOptions = {}): Promise<TenderDetail> {
  return api.get<TenderDetail>(`${BASE}/${tenderId}`, options)
}

export type ListRequirementsQuery = {
  is_mandatory?: boolean
  evaluation_impact?: EvaluationImpact
}

/**
 * `GET /api/tenders/{id}/requirements`.
 *
 * Booleans are sent as the literal `true`/`false` FastAPI parses; both filters
 * are dropped when absent so the default is "every requirement".
 */
export function listRequirements(
  tenderId: string,
  query: ListRequirementsQuery = {},
  options: CallOptions = {},
): Promise<Requirement[]> {
  const params = new URLSearchParams()

  if (query.is_mandatory !== undefined) {
    params.set('is_mandatory', String(query.is_mandatory))
  }
  if (query.evaluation_impact) {
    params.set('evaluation_impact', query.evaluation_impact)
  }

  const search = params.toString()
  return api.get<Requirement[]>(
    `${BASE}/${tenderId}/requirements${search ? `?${search}` : ''}`,
    options,
  )
}

export type ListMatchesQuery = {
  match_type?: MatchType
  review_status?: MatchReviewStatus
}

/** `GET /api/tenders/{id}/matches` — evidence matches, highest confidence first. */
export function listMatches(
  tenderId: string,
  query: ListMatchesQuery = {},
  options: CallOptions = {},
): Promise<EvidenceMatch[]> {
  const params = new URLSearchParams()

  if (query.match_type) {
    params.set('match_type', query.match_type)
  }
  if (query.review_status) {
    params.set('review_status', query.review_status)
  }

  const search = params.toString()
  return api.get<EvidenceMatch[]>(
    `${BASE}/${tenderId}/matches${search ? `?${search}` : ''}`,
    options,
  )
}

/** `GET /api/tenders/{id}/report` — computed live from the current state. */
export function getReport(tenderId: string, options: CallOptions = {}): Promise<TenderReport> {
  return api.get<TenderReport>(`${BASE}/${tenderId}/report`, options)
}

/* -------------------------------------------------------------------------- */
/* Uploading                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * `POST /api/tenders`.
 *
 * File-only: the endpoint validates + stores the PDF, creates the tender row
 * with its name defaulted to the filename, and enqueues the analysis pipeline,
 * returning 201 in milliseconds. Any tender metadata the user typed on the
 * upload screen is applied afterwards with `updateTender` (a PATCH), because the
 * upload route takes no metadata fields.
 *
 * `api.postForm` deliberately does not set Content-Type — the browser has to, so
 * that it can append the multipart boundary. A byte over 100MB, a non-PDF, or an
 * empty file comes back as a 4xx from the server; there is no client-side 409
 * duplicate concept here (unlike the library).
 */
export function uploadTender(file: File, options: CallOptions = {}): Promise<TenderUploadResponse> {
  const body = new FormData()
  body.append('file', file)
  return api.postForm<TenderUploadResponse>(BASE, body, options)
}

/* -------------------------------------------------------------------------- */
/* Editing + review                                                           */
/* -------------------------------------------------------------------------- */

/**
 * `PATCH /api/tenders/{id}` — edit tender metadata (name, reference, issuing
 * authority, sector, location, value, deadline, evaluation weighting). Only the
 * fields present in `payload` are changed; an empty `name` is a 422.
 */
export function updateTender(
  tenderId: string,
  payload: TenderUpdate,
  options: CallOptions = {},
): Promise<TenderDetail> {
  return api.patchJson<TenderDetail>(`${BASE}/${tenderId}`, payload, options)
}

/**
 * `PATCH /api/tenders/{id}/matches/{matchId}` — accept, reject, or reassign one
 * evidence match. `document_id` is required on the body for `reassign` and
 * ignored otherwise; the server 422s a reassign that omits it.
 */
export function reviewMatch(
  tenderId: string,
  matchId: string,
  payload: MatchReviewUpdate,
  options: CallOptions = {},
): Promise<EvidenceMatch> {
  return api.patchJson<EvidenceMatch>(`${BASE}/${tenderId}/matches/${matchId}`, payload, options)
}

/**
 * `POST /api/tenders/{id}/finalize` — lock the analysis in, re-assemble the
 * output from accepted matches, and move the tender to FINALIZED (which also
 * closes the progress socket). Returns the updated detail.
 */
export function finalizeTender(tenderId: string, options: CallOptions = {}): Promise<TenderDetail> {
  return api.postEmpty<TenderDetail>(`${BASE}/${tenderId}/finalize`, options)
}

/**
 * `POST /api/tenders/{id}/cancel` — stop a tender that is still being analysed.
 * Marks it FAILED with a "Stopped by user." message; the long extraction stage
 * notices and halts. Only valid while the tender is in flight (a settled tender
 * comes back as a 409).
 */
export function cancelTender(tenderId: string, options: CallOptions = {}): Promise<TenderDetail> {
  return api.postEmpty<TenderDetail>(`${BASE}/${tenderId}/cancel`, options)
}

/**
 * `POST /api/tenders/{id}/report-issue` — email a failed tender's error to the
 * support team and mark it reported. Returns the updated detail (with
 * `support_requested_at` set) so the UI can flip to the "reported, please wait"
 * state. A 503 means SMTP is not configured on the server; a 502 means the send
 * itself failed — both come back as an `ApiError` the caller can branch on to
 * offer a mailto: fallback.
 */
export function reportTenderIssue(tenderId: string, options: CallOptions = {}): Promise<TenderDetail> {
  return api.postEmpty<TenderDetail>(`${BASE}/${tenderId}/report-issue`, options)
}

/**
 * `DELETE /api/tenders/{id}` — removes the tender row and its on-disk files
 * (source PDF, output folder, output zip). Cascades delete `tender_chunks`,
 * `requirements` and `requirement_evidence_matches` at the database level.
 *
 * Allowed at any status: for a stuck or unwanted run, delete IS the fix, so
 * the endpoint deliberately does not gate on `status`. A worker still processing
 * a deleted tender hits a missing row on its next refresh and stops.
 */
export function deleteTender(tenderId: string, options: CallOptions = {}): Promise<void> {
  return api.delete<void>(`${BASE}/${tenderId}`, options)
}

/**
 * `POST /api/tenders/{id}/reprocess` — run the pipeline again for a tender that
 * failed, was stopped, or has already been reviewed. Idempotent: each pipeline
 * stage clears its own previous rows, so a retry replaces the earlier attempt.
 * A tender that is still running comes back as a 409 — stop it first.
 */
export function reprocessTender(tenderId: string, options: CallOptions = {}): Promise<TenderDetail> {
  return api.postEmpty<TenderDetail>(`${BASE}/${tenderId}/reprocess`, options)
}

/* -------------------------------------------------------------------------- */
/* URLs                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * `POST /api/tenders/{id}/ws-ticket` — mints a short-lived (60s), single-use
 * ticket for the progress socket below. Call this right before opening the
 * WebSocket, then pass the ticket straight to `tenderProgressUrl`; minting one
 * and holding onto it doesn't help, since it expires almost immediately and
 * can only ever be redeemed once.
 *
 * This is a normal authenticated POST, so `apiClient` attaches the real
 * bearer token the ordinary way — the whole point is to keep that token out
 * of the WebSocket URL that follows.
 */
export function mintTenderWsTicket(tenderId: string, options: CallOptions = {}): Promise<string> {
  return api
    .postEmpty<{ ticket: string }>(`${BASE}/${tenderId}/ws-ticket`, options)
    .then((res) => res.ticket)
}

/**
 * The tender progress socket: `/ws/tenders/{id}/progress?ticket=<ticket>`.
 *
 * Not under `/api` — it is mounted at the root, so prefixing it with BASE gives a
 * 404 that looks like a broken socket. This one REQUIRES a ticket: a browser
 * cannot set an Authorization header on a `WebSocket`, so the server redeems a
 * one-shot ticket (minted a moment earlier via `mintTenderWsTicket`) from a
 * `ticket` query parameter and closes the connection with 1008 if it is
 * missing, expired, already used, or was minted for a different tender. The
 * caller passes the ticket it just minted; when it is null the connection will
 * be refused and the hook falls back to polling.
 *
 * On connect the server replays the latest progress from Redis immediately, so a
 * reconnect mid-run is caught up rather than staring at a blank bar.
 */
export function tenderProgressUrl(tenderId: string, ticket: string | null): string {
  const base = websocketUrl(`/ws/tenders/${tenderId}/progress`)
  return ticket ? `${base}?ticket=${encodeURIComponent(ticket)}` : base
}

/**
 * The source PDF: `GET /api/tenders/{id}/file`, served inline.
 *
 * THIS CANNOT GO STRAIGHT TO react-pdf's `file` PROP or an `<a href>`: the route
 * requires a bearer token, and a browser fetching from `src`/`href` sends none,
 * so the request 403s. Use `fetchTenderFileObjectUrl` and pass the object URL
 * instead. Exported because that helper needs the path in one place.
 */
export function tenderFileUrl(tenderId: string): string {
  return `${BASE}/${tenderId}/file`
}

/** The assembled output zip: `GET /api/tenders/{id}/download`. Same auth caveat. */
export function tenderDownloadUrl(tenderId: string): string {
  return `${BASE}/${tenderId}/download`
}

/* -------------------------------------------------------------------------- */
/* Authenticated binary reads                                                 */
/* -------------------------------------------------------------------------- */

/**
 * The source PDF, fetched with the bearer token attached and turned into a
 * `blob:` URL react-pdf will accept.
 *
 * THE CALLER OWNS THE URL AND MUST REVOKE IT — a PDF blob is megabytes and the
 * browser holds it until told otherwise. Pair with `releaseObjectUrl` in an
 * effect cleanup, and revoke immediately on the path where the fetch resolves
 * after the component unmounted.
 */
export async function fetchTenderFileObjectUrl(
  tenderId: string,
  options: CallOptions = {},
): Promise<string> {
  const blob = await api.getBlob(tenderFileUrl(tenderId), options)
  return URL.createObjectURL(blob)
}

/**
 * The output zip, fetched with the token attached and turned into a `blob:` URL
 * an `<a download>` can point at. Same ownership rule as above: revoke it once
 * the download has been triggered.
 */
export async function fetchTenderOutputObjectUrl(
  tenderId: string,
  options: CallOptions = {},
): Promise<string> {
  const blob = await api.getBlob(tenderDownloadUrl(tenderId), options)
  return URL.createObjectURL(blob)
}

/**
 * Releases an object URL, tolerating null — so cleanup reads as one line and a
 * double revoke (harmless) needs no bookkeeping. Local to this module rather than
 * imported from the document service, keeping the two features independent.
 */
export function releaseObjectUrl(url: string | null | undefined): void {
  if (url) {
    URL.revokeObjectURL(url)
  }
}
