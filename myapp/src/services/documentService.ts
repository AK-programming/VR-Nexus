/**
 * Every call the Evidence Library exposes, in one module.
 *
 * Ported from `VR_Project/frontend/js/app.js`, which spoke to this same API without a
 * build step. The harness had one `api()` helper and inline `fetch` paths; this splits
 * them into named functions so a page asks for what it wants rather than assembling a
 * URL, and so a rename on the backend is one edit here instead of a search across
 * pages.
 *
 * Error shapes are already handled by `apiClient`: it unwraps `detail` as a string, a
 * validation array, or an object with `message`, which is exactly the three shapes
 * this API returns. So nothing here catches — a caller that wants a message calls
 * `errorMessage`, and a caller that wants to branch on a 409 reads `error.status`.
 *
 * Two 409s come out of this API and they are not the same thing. Upload returns one for
 * a byte-identical file, with the existing document under `detail.duplicate`; retrain
 * returns one when a worker already holds the document, which is a "try again in a
 * moment", not a rejection. Any caller that branches on 409 should know which it asked
 * for.
 *
 * Every route here is authenticated. All fifteen declare
 * `user: User = Depends(get_current_user)`, and that dependency reads a bearer token from
 * the Authorization header and nowhere else — no query-parameter fallback, no cookie. It
 * replaced the `DEV_PRINCIPAL` stub the standalone Section 6 backend shipped, which
 * returned a fixed principal and could not fail.
 *
 * The calls in this file need nothing extra, because `apiClient` attaches the token to
 * everything it sends. The two routes that return *bytes* rather than JSON are the ones
 * that need care, since the obvious way to use them — handing a URL to `<img src>` or to
 * react-pdf — makes the browser issue the request itself, without the header. Use
 * `fetchDocumentFileObjectUrl` and `fetchDocumentImageObjectUrl` at the bottom of this
 * file for those.
 *
 * Note which status code arrives. A request with no Authorization header at all is
 * rejected by HTTPBearer with **403**, not 401, so it never reaches the client's
 * refresh-and-retry. Only an expired or malformed token produces the 401 that does. A 403
 * from a library route therefore means "not signed in", not "insufficient role".
 */

import { api, websocketUrl, type CallOptions } from '@/lib/apiClient'
import type {
  DocumentCategory,
  DocumentTrainingStatus,
  DuplicateCheckResult,
  IndexJob,
  LibraryDocument,
  LibraryDocumentDetail,
  LibraryStats,
  StageOption,
  TrainResponse,
  UploadMetadata,
  UploadResponse,
} from '@/models/documents'
import { toUploadFormData } from '@/models/documents'

const BASE = '/api/library'

/* -------------------------------------------------------------------------- */
/* Reading                                                                    */
/* -------------------------------------------------------------------------- */

export type ListDocumentsQuery = {
  category?: DocumentCategory
  /**
   * The wire parameter is `status`, aliased from `doc_status` on the server. Sending
   * `doc_status` looks right and is silently ignored, which returns every document
   * and makes a broken filter look like a filter with nothing to do.
   */
  status?: DocumentTrainingStatus
  /** Server bounds: 1-500, default 100. */
  limit?: number
  offset?: number
}

/**
 * `GET /documents`, newest first.
 *
 * Undefined values are dropped rather than sent empty. `?category=` with no value is
 * a 422 from FastAPI's enum coercion, not an absent filter.
 */
export function listDocuments(
  query: ListDocumentsQuery = {},
  options: CallOptions = {},
): Promise<LibraryDocument[]> {
  const params = new URLSearchParams()

  if (query.category) {
    params.set('category', query.category)
  }
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
  return api.get<LibraryDocument[]>(`${BASE}/documents${search ? `?${search}` : ''}`, options)
}

/**
 * `GET /documents/{id}`.
 *
 * `includeChunks` is off by default and should stay off for anything that renders a
 * summary: a long tender parses into hundreds of chunks, and pulling their full text
 * to show a page count is a few megabytes for nothing.
 */
export function getDocument(
  documentId: string,
  includeChunks = false,
  options: CallOptions = {},
): Promise<LibraryDocumentDetail> {
  const query = includeChunks ? '?include_chunks=true' : ''
  return api.get<LibraryDocumentDetail>(`${BASE}/documents/${documentId}${query}`, options)
}

/** `GET /stats` — per-category counts by status, plus the embedding model in use. */
export function getStats(options: CallOptions = {}): Promise<LibraryStats> {
  return api.get<LibraryStats>(`${BASE}/stats`, options)
}

/**
 * `GET /stages`.
 *
 * The endpoint exists so a client does not hardcode the pipeline. This one does have
 * the stages compiled in — the timeline needs to draw the *whole* track before a job
 * reports anything, so it cannot wait to be told — but fetching these lets a screen
 * label a stage with the server's own wording and notice if the two have drifted.
 */
export function listStages(options: CallOptions = {}): Promise<{ stages: StageOption[] }> {
  return api.get<{ stages: StageOption[] }>(`${BASE}/stages`, options)
}

/* -------------------------------------------------------------------------- */
/* Uploading                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * `POST /{category}/upload`.
 *
 * Multipart, and `api.postForm` deliberately does not set Content-Type — the browser
 * has to, so that it can append the boundary. Setting it by hand is the classic cause
 * of a 422 on an upload that looks perfectly correct.
 *
 * A byte-identical file already in the library comes back as **409**, with the
 * existing document under `detail.duplicate`. That is a rejection, not a warning. A
 * merely *similar* file uploads successfully and carries `duplicate_warning` instead,
 * which is for a person to judge.
 *
 * Uploading does not index. `train` below is a separate call on purpose: the
 * duplicate check has to happen before anything is parsed or embedded.
 */
export function uploadDocument(
  category: DocumentCategory,
  file: File,
  metadata: UploadMetadata,
  options: CallOptions = {},
): Promise<UploadResponse> {
  return api.postForm<UploadResponse>(
    `${BASE}/${category}/upload`,
    toUploadFormData(file, metadata),
    options,
  )
}

/**
 * `POST /check-duplicate` — a dry run that stores nothing.
 *
 * Lets the UI warn while a file is still sitting in the drop zone, which is the only
 * point at which the warning is still cheap to act on.
 */
export function checkDuplicate(
  file: File,
  category?: DocumentCategory,
  options: CallOptions = {},
): Promise<DuplicateCheckResult> {
  const body = new FormData()
  body.append('file', file)
  if (category) {
    body.append('category', category)
  }

  return api.postForm<DuplicateCheckResult>(`${BASE}/check-duplicate`, body, options)
}

/* -------------------------------------------------------------------------- */
/* Indexing                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * `POST /train` — queues indexing jobs and returns one per document that started.
 *
 * An empty `documentIds` trains everything currently queued, which is what the
 * "Train all" affordance sends. `force` re-indexes documents that are already
 * indexed; without it they come back under `skipped`, and so does anything a worker
 * currently holds — the server will not start a second job over a running one.
 *
 * `skipped` is not an error. A page that treats it as one will show a failure for the
 * entirely normal case of pressing Train twice.
 */
export function train(
  documentIds: string[] = [],
  force = false,
  options: CallOptions = {},
): Promise<TrainResponse> {
  const query = force ? '?force=true' : ''
  return api.postJson<TrainResponse>(`${BASE}/train${query}`, { document_ids: documentIds }, options)
}

/** `POST /documents/{id}/retrain`. 409 if a worker already holds this document. */
export function retrainDocument(documentId: string, options: CallOptions = {}): Promise<IndexJob> {
  return api.postEmpty<IndexJob>(`${BASE}/documents/${documentId}/retrain`, options)
}

/** `GET /jobs/{id}` — the polling fallback for when the socket is unavailable. */
export function getJob(jobId: string, options: CallOptions = {}): Promise<IndexJob> {
  return api.get<IndexJob>(`${BASE}/jobs/${jobId}`, options)
}

/** `GET /documents/{id}/jobs` — every run over one document, for its history. */
export function listDocumentJobs(
  documentId: string,
  options: CallOptions = {},
): Promise<IndexJob[]> {
  return api.get<IndexJob[]>(`${BASE}/documents/${documentId}/jobs`, options)
}

/** `DELETE /documents/{id}`. 204, no body. */
export function deleteDocument(documentId: string, options: CallOptions = {}): Promise<void> {
  return api.delete(`${BASE}/documents/${documentId}`, options)
}

/* -------------------------------------------------------------------------- */
/* Composed reads                                                             */
/* -------------------------------------------------------------------------- */

/**
 * A document that is not finished, paired with its most recent indexing run.
 *
 * `job` is null when the document has a status but no job row — which happens for
 * anything uploaded and never trained, since `queued` is the status a document is
 * *born* with, not something `/train` sets. That distinction is the difference between
 * "waiting for a worker" and "nobody has pressed Train", and the queue says so.
 */
export interface QueueEntry {
  document: LibraryDocument
  job: IndexJob | null
}

/**
 * The statuses worth putting on a processing screen: everything except `indexed`.
 *
 * Fetched as separate requests because `GET /documents` takes a single `status` value,
 * not a list. Five small filtered reads beat one unfiltered read of the whole library
 * and a client-side filter, which is what the old harness did with `limit=100` and no
 * filter at all — on a library of any size that silently stops showing the jobs you
 * came to watch.
 */
const QUEUE_STATUSES: readonly DocumentTrainingStatus[] = [
  'parsing',
  'tagging',
  'embedding',
  'queued',
  'failed',
]

/**
 * How many documents the queue will fetch jobs for.
 *
 * The API has no "list all jobs" route — only `/jobs/{id}` and
 * `/documents/{id}/jobs` — so the newest job per document costs one request per
 * document. That fan-out has to be bounded or a library with hundreds of failed
 * documents opens the page with hundreds of requests. Sixty is well past what anyone
 * reads on one screen, and the entries are taken newest-first so the cut falls on the
 * oldest, least interesting rows.
 */
const QUEUE_LIMIT = 60

/**
 * Everything currently in the pipeline, newest first, each with its latest job.
 *
 * Derived from server state rather than from a list of jobs this browser tab happened
 * to start, which is the important difference from the old harness: reload the page,
 * open it in a second tab, or come back tomorrow to a job someone else queued, and the
 * queue is still right. The harness's `#job-list` only ever held jobs from the current
 * session and was empty on every refresh.
 *
 * A failure to read one document's job history is swallowed to `null` rather than
 * failing the whole queue. One 404 — a document deleted between the two round trips —
 * should cost that row its progress bar, not take the page down.
 */
export async function listProcessingQueue(options: CallOptions = {}): Promise<QueueEntry[]> {
  const byStatus = await Promise.all(
    QUEUE_STATUSES.map((status) => listDocuments({ status, limit: 100 }, options)),
  )

  /* Deduplicated even though a document holds exactly one status and cannot appear
     twice: the reads are not a single transaction, so a document that moves from
     `parsing` to `tagging` between two of them is returned by both. Without this it
     renders as two rows for the same document. */
  const seen = new Set<string>()
  const documents: LibraryDocument[] = []

  byStatus.flat().forEach((document) => {
    if (seen.has(document.id)) {
      return
    }
    seen.add(document.id)
    documents.push(document)
  })

  documents.sort((a, b) => b.created_at.localeCompare(a.created_at))

  const visible = documents.slice(0, QUEUE_LIMIT)

  const jobs = await Promise.all(
    visible.map((document) =>
      listDocumentJobs(document.id, options).catch(() => [] as IndexJob[]),
    ),
  )

  return visible.map((document, index) => {
    /* `/documents/{id}/jobs` has no documented ordering, so newest is picked rather
       than assumed. `updated_at` is ISO-8601 with a fixed offset, which makes string
       comparison the same answer as date comparison and avoids parsing a Date per
       row. */
    const history = jobs[index] ?? []
    const latest = history.reduce<IndexJob | null>(
      (newest, job) => (newest === null || job.updated_at > newest.updated_at ? job : newest),
      null,
    )

    return { document, job: latest }
  })
}


/* -------------------------------------------------------------------------- */
/* URLs                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * Where the progress socket lives: `/ws/library/{job_id}`.
 *
 * Note the path is *not* under `/api`. It is mounted at the root, so prefixing it
 * with BASE gives a 404 that looks like a broken WebSocket.
 *
 * On connect the server replays the job's persisted row as a snapshot flagged
 * `replayed`, then closes immediately if the job is already terminal. It sends
 * `{"type":"ping"}` on idle, and `{"error": ...}` followed by a close if Redis is
 * unreachable — at which point the client is expected to poll `getJob`.
 *
 * This socket takes no credential, which is worth knowing rather than leaning on. Every
 * HTTP route under `/api/library` requires a bearer token, and the *tender* progress socket
 * authenticates with `?token=<access_token>` — a query parameter precisely because a
 * browser cannot put a header on a `WebSocket` — but `/ws/library/{job_id}` accepts the
 * connection and starts streaming to anyone holding a job id. That reads as an
 * inconsistency on the backend rather than a decision this file should encode, so nothing
 * is appended here. If the route grows a `token` parameter to match the tender side, this
 * function is the only place that changes.
 */
export function jobProgressUrl(jobId: string): string {
  return websocketUrl(`/ws/library/${jobId}`)
}

/**
 * An image the parser extracted, by name: `GET /documents/{id}/images/{name}`.
 *
 * The server rejects any path syntax in the name — a slash, a backslash or a leading
 * dot is a 400 — so `image_paths` entries are passed through verbatim and encoded, not
 * joined with anything. That check exists because the name here *is* user-facing input;
 * `documentFileUrl` below needs no equivalent, since nothing from the request reaches
 * the filesystem on that route.
 *
 * THIS CANNOT GO IN AN `<img src>`. The route requires a bearer token in the
 * Authorization header, and a browser fetching an image from an `src` attribute sends no
 * such header — the request 403s and the element renders as a broken image. Use
 * `fetchDocumentImageObjectUrl` below. This builder is exported because that helper and
 * the tests both need the path in one place, not because the string is usable on its own.
 */
export function documentImageUrl(documentId: string, imageName: string): string {
  return `${BASE}/documents/${documentId}/images/${encodeURIComponent(imageName)}`
}

/**
 * The stored upload itself: `GET /documents/{id}/file`.
 *
 * The route was carried into the merged backend from the flat prototype's tree, where it
 * was the one library endpoint the prototype had and maryam's did not.
 * `documents.file_path` was written at upload and read by the worker, but nothing served
 * it — so for a while there was deliberately no helper here, because a plausible-looking
 * URL pointing at a route that 404s is worse than no helper at all: the viewer reports
 * the failure as "this file could not be opened" and blames the document for the API's
 * missing route.
 *
 * The path is still not a field on `DocumentOut`, and should not become one. It is a
 * server-side location under LIBRARY_STORAGE_DIR; the id is the handle and the route
 * resolves it.
 *
 * Served inline with the row's real media type, so what comes back is a PDF a viewer can
 * open rather than an attachment.
 *
 * THIS CANNOT GO STRAIGHT TO react-pdf'S `file` PROP, for the same reason as the image
 * URL above: react-pdf fetches the URL itself, without the Authorization header, and gets
 * a 403 — which it surfaces as a generic failed-to-load message. Use
 * `fetchDocumentFileObjectUrl` below and pass react-pdf the object URL instead. A
 * download anchor has the same problem: fetch the blob, then point `download` at the
 * object URL.
 *
 * Two things this route does not promise. It is only worth rendering as a PDF when the
 * upload is one — a `.docx` or a `.pptx` returns its own bytes and renders as nothing —
 * and it can 404 even for a document that exists, because rows live in Postgres while
 * files live on a separate volume and the two can be wiped independently.
 */
export function documentFileUrl(documentId: string): string {
  return `${BASE}/documents/${documentId}/file`
}

/* -------------------------------------------------------------------------- */
/* Authenticated binary reads                                                 */
/* -------------------------------------------------------------------------- */

/**
 * The two routes above, fetched properly.
 *
 * A URL in an `<img src>`, an `<a href>` or react-pdf's `file` prop is fetched by the
 * browser, and the browser attaches nothing this app configured — no bearer token, so a
 * 403 from `HTTPBearer` and a broken image or a viewer that will not load. The only way to
 * get a header onto the request is to make the request in JavaScript, which is what these
 * do: `api.getBlob` sends the token, participates in the single-flight refresh, and hands
 * back bytes. `URL.createObjectURL` then turns those bytes into a `blob:` URL that any of
 * those three consumers will accept, because reading it involves no network at all.
 *
 * THE CALLER OWNS THE URL AND MUST REVOKE IT. An object URL is a reference the browser
 * holds until told otherwise, and the blob behind a PDF is megabytes. Forget the revoke
 * and every document a user opens stays in memory until the tab closes. `releaseObjectUrl`
 * below is the other half; call it in an effect cleanup, and also on the path where a
 * fetch resolves after the component has already unmounted — awaiting means the URL can be
 * created a moment *after* cleanup ran, so the flag has to be checked and the fresh URL
 * revoked immediately rather than stored.
 *
 * Passing a `signal` is still worth doing. It will not prevent that race, but it stops a
 * navigated-away-from PDF from finishing its download.
 */
export async function fetchDocumentFileObjectUrl(
  documentId: string,
  options: CallOptions = {},
): Promise<string> {
  const blob = await api.getBlob(documentFileUrl(documentId), options)
  return URL.createObjectURL(blob)
}

/** The same, for one extracted image. See the note above about owning the URL. */
export async function fetchDocumentImageObjectUrl(
  documentId: string,
  imageName: string,
  options: CallOptions = {},
): Promise<string> {
  const blob = await api.getBlob(documentImageUrl(documentId, imageName), options)
  return URL.createObjectURL(blob)
}

/**
 * Releases an object URL, tolerating null.
 *
 * Exists so cleanup reads as one line: the state holding one of these starts as null and
 * is null again between documents, and `URL.revokeObjectURL(null)` is a type error rather
 * than a no-op. Revoking twice is harmless, so a cleanup that also ran on an early return
 * needs no bookkeeping.
 */
export function releaseObjectUrl(url: string | null | undefined): void {
  if (url) {
    URL.revokeObjectURL(url)
  }
}

