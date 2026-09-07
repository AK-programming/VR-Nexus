/**
 * The Evidence Library wire contract, mirrored from the FastAPI service.
 *
 * Every type here has a counterpart in the single merged backend: the response models
 * live in `backend/app/schemas/library.py`, the columns behind them in
 * `backend/app/models/document.py` and `chunk.py`, and the enums in
 * `backend/app/models/enums.py`. (The flat `app/schemas.py` and `app/models.py` this
 * file was first written against are tombstoned — they raise on import, and a package
 * of the same name shadows them anyway.) Field names stay snake_case for the same
 * reason `auth.ts` keeps them: that is what crosses the wire, and renaming them in the
 * client would mean a mapping layer that earns nothing and hides drift when the API
 * changes.
 *
 * The enums are `as const` arrays rather than TS enums because tsconfig sets
 * erasableSyntaxOnly — an enum emits runtime code and cannot be stripped by Vite's
 * transpiler. Each array doubles as the source of its union type and as something a
 * filter bar can iterate.
 *
 * Nullability here is the server's, not a defensive guess. `DocumentOut` runs a
 * `_blank_if_none` validator over every nullable string column (`client`, `sector`,
 * `service_line`, `geography`, `training_error`, `title`) and `_empty_list_if_none` over
 * both list fields; `original_filename` and `doc_type` carry no validator because the
 * columns are `nullable=False` and cannot arrive as NULL in the first place. Between the
 * two, no string or array on this contract can be null. `page_count`/`chunk_count` are
 * required ints. So those are plain `string`, `string[]` and `number`. Writing `| null`
 * "to be safe" is not free: it forces a `??` at every call site to defend against a value
 * the API cannot send, and the noise hides the one field that *is* nullable. `indexed_at`
 * is that field, because a document that has never finished indexing genuinely has no
 * timestamp.
 *
 * Read the "not on the wire" section at the bottom before adding a field. Several
 * values a document screen would like — a file's size, who uploaded it, a summary — are
 * not returned by this API at all, and inventing them here is how a UI ends up rendering
 * `undefined` against a live backend.
 *
 * Keep this file free of React and free of fetch. It describes shapes only.
 */

/* -------------------------------------------------------------------------- */
/* Categories                                                                 */
/* -------------------------------------------------------------------------- */

/** Backend `DocumentCategory(str, enum.Enum)`. These three, and no others. */
export const DOCUMENT_CATEGORIES = ['case_study', 'methodology', 'company_document'] as const

export type DocumentCategory = (typeof DOCUMENT_CATEGORIES)[number]

/**
 * How a category is written on screen.
 *
 * The mockups label `case_study` as "Tender / RFP", and the sample library really is
 * DPL case studies, so the truthful label wins — a document titled "NLC Terminal
 * Operating System" filed under "Tender / RFP" would teach the reader to distrust
 * the column. Change the string here and every table, filter and badge follows; it
 * is one edit, on purpose.
 */
export const CATEGORY_LABELS: Record<DocumentCategory, string> = {
  case_study: 'Case Study',
  methodology: 'Methodology',
  company_document: 'Company Document',
}

/* -------------------------------------------------------------------------- */
/* File types                                                                 */
/* -------------------------------------------------------------------------- */

/** Backend `DocumentFileType`. Note that every image format collapses to `image`. */
export const DOCUMENT_FILE_TYPES = ['pdf', 'docx', 'pptx', 'image'] as const

export type DocumentFileType = (typeof DOCUMENT_FILE_TYPES)[number]

/**
 * The extensions `storage.validate_upload` accepts, restated so the drop zone can
 * refuse a file without spending a round trip on it.
 *
 * The server validates by *extension*, not MIME type — its own tests assert that a
 * `.pptx` sent as `application/octet-stream` is accepted. So the map below lists
 * extensions against each MIME type rather than relying on the browser's guess,
 * which is what lets react-dropzone match either way.
 */
export const DROPZONE_ACCEPT: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'],
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
  'image/tiff': ['.tiff', '.tif'],
}

/** Human list for the drop zone's hint line. Kept in step with the map above. */
export const ACCEPTED_EXTENSIONS = 'PDF, DOCX, PPTX, PNG, JPG, TIFF'

/** Backend `MAX_UPLOAD_MB: int = 100`. */
export const MAX_UPLOAD_MB = 100

export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

/** Which glyph a row draws for its file type. The component maps name to icon. */
export type FileGlyphName = 'document' | 'slides' | 'image'

export const FILE_TYPE_GLYPHS: Record<DocumentFileType, FileGlyphName> = {
  pdf: 'document',
  docx: 'document',
  pptx: 'slides',
  image: 'image',
}

/**
 * The file type a name implies, matching the server's own rule.
 *
 * `GET /documents` returns no file type field, and a file sitting in the drop zone has
 * not been given an id yet — so both the table and the upload list have to work it out
 * from the filename. Extension, not the browser's MIME guess, because that is exactly
 * what `storage.validate_upload` does: its tests assert a `.pptx` arriving as
 * `application/octet-stream` is accepted, so trusting the MIME type here would refuse
 * files the server would take.
 *
 * Returns null for anything outside the accepted set, which is what the drop zone
 * shows as "not a supported file" rather than guessing at a glyph.
 */
export function fileTypeFromName(filename: string): DocumentFileType | null {
  const extension = filename.slice(filename.lastIndexOf('.')).toLowerCase()

  switch (extension) {
    case '.pdf':
      return 'pdf'
    case '.docx':
      return 'docx'
    case '.pptx':
      return 'pptx'
    case '.png':
    case '.jpg':
    case '.jpeg':
    case '.tiff':
    case '.tif':
      return 'image'
    default:
      return null
  }
}

/* -------------------------------------------------------------------------- */
/* Training status                                                            */
/* -------------------------------------------------------------------------- */

/** Backend `DocumentTrainingStatus`. What a document *is*, as opposed to what a job is doing. */
export const TRAINING_STATUSES = [
  'queued',
  'parsing',
  'tagging',
  'embedding',
  'indexed',
  'failed',
] as const

export type DocumentTrainingStatus = (typeof TRAINING_STATUSES)[number]

/**
 * Labels are written out rather than derived from the value. Prettifying `indexed`
 * gives "Indexed", which is accurate but says nothing to a reader who does not know
 * the pipeline; "Ready" is what they actually want to know.
 */
export const TRAINING_STATUS_LABELS: Record<DocumentTrainingStatus, string> = {
  queued: 'Queued',
  parsing: 'Parsing',
  tagging: 'Tagging',
  embedding: 'Embedding',
  indexed: 'Ready',
  failed: 'Failed',
}

/**
 * The three statuses that mean "a worker currently holds this document".
 *
 * Mirrors `_IN_FLIGHT` in library.py, which is what makes `/train` and `/retrain`
 * return 409 rather than starting a second job over the top of a running one. The UI
 * uses it to disable the same buttons the server would refuse.
 */
export const IN_FLIGHT_STATUSES: readonly DocumentTrainingStatus[] = [
  'parsing',
  'tagging',
  'embedding',
]

export function isInFlight(status: DocumentTrainingStatus): boolean {
  return IN_FLIGHT_STATUSES.includes(status)
}

/* -------------------------------------------------------------------------- */
/* Job stages                                                                 */
/* -------------------------------------------------------------------------- */

/** Backend `JobStage`. What a running indexing job reports. */
export const JOB_STAGES = [
  'queued',
  'parsing',
  'tagging',
  'embedding',
  'complete',
  'failed',
] as const

export type JobStage = (typeof JOB_STAGES)[number]

/** Backend `STAGE_LABELS`, verbatim. `GET /stages` serves the same pairs. */
export const STAGE_LABELS: Record<JobStage, string> = {
  queued: 'Queued',
  parsing: 'Parsing',
  tagging: 'Tagging',
  embedding: 'Generating Embeddings',
  complete: 'Indexing Complete',
  failed: 'Failed',
}

/**
 * The nodes the timeline draws, in order.
 *
 * `failed` is deliberately absent. It is not a sixth step, it is what happens
 * instead of one — drawing it as a node would leave a permanently grey box on every
 * successful job, which is the clearest possible way to make a healthy pipeline look
 * broken. A failure is rendered by marking the stage that was active when it
 * happened, which is the only place a reader can act on it.
 *
 * These five are the *only* values a real job emits, so the timeline can never show
 * a stage the API will not send. The mockup's "Splitting into Chunks" and "Indexing"
 * have no backend stage behind them and would never light up.
 */
export const STAGE_SEQUENCE = ['queued', 'parsing', 'tagging', 'embedding', 'complete'] as const

export type TimelineStage = (typeof STAGE_SEQUENCE)[number]

/**
 * One line saying what each stage is doing, for the reader who is watching a
 * progress bar and wondering what it is waiting for. Present tense while it runs
 * reads better than a noun, so these are phrased as actions.
 */
export const STAGE_DESCRIPTIONS: Record<TimelineStage, string> = {
  queued: 'Waiting for a worker to pick the document up.',
  parsing: 'Reading the file and pulling out text, tables and images.',
  tagging: 'Inferring client, sector, service line and keywords.',
  embedding: 'Turning each passage into a vector the search can match on.',
  complete: 'Indexed and searchable.',
}

/** How a timeline node is drawn. Derived, never stored. */
export type StageState = 'done' | 'active' | 'pending' | 'failed'

/**
 * Which state each node is in, given where a job has got to.
 *
 * This is the harness's `renderJob` logic, ported: find the reported stage in the
 * sequence, mark everything before it done and everything after it pending. Three
 * details that are easy to get wrong and all matter:
 *
 *   `complete` is marked done, not active. It is the only entry that is an end state
 *   rather than a piece of work, and leaving it "active" would spin a dot forever on
 *   a job that has finished.
 *
 *   A failed job's own `stage` is `failed`, which is not in the sequence — the step
 *   it died on is not stored anywhere. So the caller passes `failedAt` when it knows,
 *   which it does whenever it watched the progress stream, and the node that stopped
 *   is marked while the ones before it stay ticked, because they genuinely did
 *   succeed.
 *
 *   Without `failedAt` the whole track reads pending rather than blaming a step at
 *   random. A job loaded cold from `GET /jobs/{id}` after a failure has no stage
 *   history, and a red mark on the wrong node sends the reader to the wrong log.
 */
export function stageStates(stage: JobStage, failedAt?: TimelineStage): Record<TimelineStage, StageState> {
  const states = {} as Record<TimelineStage, StageState>

  if (stage === 'failed') {
    const failedIndex = failedAt ? STAGE_SEQUENCE.indexOf(failedAt) : -1

    STAGE_SEQUENCE.forEach((value, index) => {
      if (failedIndex < 0) {
        states[value] = 'pending'
      } else if (index < failedIndex) {
        states[value] = 'done'
      } else if (index === failedIndex) {
        states[value] = 'failed'
      } else {
        states[value] = 'pending'
      }
    })

    return states
  }

  const currentIndex = STAGE_SEQUENCE.indexOf(stage)

  STAGE_SEQUENCE.forEach((value, index) => {
    if (index < currentIndex) {
      states[value] = 'done'
    } else if (index === currentIndex) {
      states[value] = value === 'complete' ? 'done' : 'active'
    } else {
      states[value] = 'pending'
    }
  })

  return states
}

/** True once a job will send nothing further. Mirrors ws.py's `TERMINAL_STAGES`. */
export function isTerminalStage(stage: JobStage): boolean {
  return stage === 'complete' || stage === 'failed'
}

/* -------------------------------------------------------------------------- */
/* Responses                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Backend `DocumentOut`.
 *
 * `id` is a UUID, `created_at` and `indexed_at` are ISO-8601 timestamps; all three
 * arrive as strings over JSON and are parsed at the point of use.
 *
 * Every string field is a string, never null — see the note at the top of this file.
 * `title` can still be `""`, which is why the UI falls back to `original_filename`
 * rather than trusting it.
 *
 * `auto_tagged_fields` lists the names of the fields the tagger filled in rather
 * than the uploader — so the UI can mark a value as inferred, which is the
 * difference between a sector the reader typed and one a model guessed.
 */
export interface LibraryDocument {
  id: string
  original_filename: string
  category: DocumentCategory
  title: string
  doc_type: string
  client: string
  sector: string
  service_line: string
  geography: string
  keywords: string[]
  auto_tagged_fields: string[]
  training_status: DocumentTrainingStatus
  page_count: number
  chunk_count: number
  training_error: string
  created_at: string
  indexed_at: string | null
}

/** Backend `ChunkOut`. One passage of a parsed document. */
export interface DocumentChunk {
  id: string
  chunk_index: number
  content: string
  section_name: string
  phase: string
  page_number: number
  token_count: number
  image_paths: string[]
}

/** Backend `DocumentDetailOut` — a document plus its chunks, when asked for them. */
export interface LibraryDocumentDetail extends LibraryDocument {
  chunks: DocumentChunk[]
}

/** Backend `JobOut`. One indexing run over one document. */
export interface IndexJob {
  id: string
  document_id: string
  stage: JobStage
  /** 0-100, as an integer. */
  progress: number
  message: string
  updated_at: string
}

/**
 * What arrives over `/ws/library/{job_id}`.
 *
 * The socket is the authority here, not the schema. `app/schemas/library.py` does define a
 * `ProgressEvent`, but it is never a `response_model` and nothing serialises through it —
 * `library_ws.py` calls `send_json` on plain dicts. Three shapes come down this socket and
 * the schema describes only the first:
 *
 *   the live event   built by `library_progress.publish` — the six fields below.
 *   the snapshot     the same six plus `replayed: true`, built by `library_ws._snapshot`
 *                    from the persisted `index_jobs` row and sent once on connect.
 *   ping and error   `{ type: 'ping', job_id }` on an idle connection, and
 *                    `{ error, job_id }` when the job id is unknown or Redis is
 *                    unreachable. Neither has a `stage`, so both are filtered in
 *                    `useJobProgress` before anything reads them as progress; parsed as
 *                    an event, a ping would blank the timeline.
 *
 * `label` is the server's own wording for the stage, so a stage renamed on the backend
 * does not need this client redeployed to read correctly.
 */
export interface ProgressEvent {
  job_id: string
  document_id: string
  stage: JobStage
  label: string
  progress: number
  message: string
  /** Set on the snapshot the socket replays when it opens mid-job. */
  replayed?: boolean
}

/** Backend `DuplicateMatch`. `similarity` is 0-1. */
export interface DuplicateMatch {
  document_id: string
  original_filename: string
  title: string
  similarity: number
}

/**
 * Backend `DuplicateCheckResult`.
 *
 * An exact match is a byte-identical file and the upload is refused with a 409. Near
 * matches do not block anything — the upload succeeds and this rides along as a
 * warning, because "similar to something we already have" is a judgement for a
 * person to make.
 */
export interface DuplicateCheckResult {
  is_exact: boolean
  exact_match: DuplicateMatch | null
  near_matches: DuplicateMatch[]
}

/** Backend `UploadResponse`. */
export interface UploadResponse {
  document: LibraryDocument
  duplicate_warning: DuplicateCheckResult | null
}

/** Backend `TrainResponse`. `skipped` names documents already indexed or in flight. */
export interface TrainResponse {
  jobs: IndexJob[]
  skipped: string[]
}

/**
 * One category's counts, as `/stats` reports them.
 *
 * Every status key is always present: the endpoint seeds all six to zero before
 * counting, so a category with nothing in it returns zeros rather than an absent key.
 * That is what makes the indexed access below safe without a fallback.
 */
export type CategoryCounts = Record<DocumentTrainingStatus, number> & { total: number }

/**
 * Backend `GET /stats`.
 *
 * Counts only. There is no byte total here and no per-document size anywhere in the
 * API, which is why "Total Size" is not a card on any screen — see the "not on the
 * wire" note at the bottom of this file.
 *
 * The endpoint has no `response_model`, so it is absent from the OpenAPI schema and
 * this type is hand-written from `library.py`'s return statement rather than generated.
 * All three category keys are always present for the same reason the status keys are.
 */
export interface LibraryStats {
  categories: Record<DocumentCategory, CategoryCounts>
  chunk_count: number
  embedding_model: string
  embedding_dim: number
  llm_available: boolean
}

/** Library-wide totals. Every figure is a sum across categories — see `rollUpStats`. */
export interface StatsRollup {
  total: number
  indexed: number
  failed: number
  queued: number
  /** Held by a worker right now: parsing, tagging or embedding. */
  processing: number
  /** Everything not yet finished, successfully or otherwise: queued + processing. */
  active: number
}

/**
 * Collapses the per-category buckets into library-wide totals.
 *
 * `/stats` only reports counts broken down by category and status, so every headline
 * figure on the overview is a sum computed here. It lives in this file rather than in
 * the page because the same numbers appear on the overview cards and in the section
 * subtitle, and two independent reductions over the same object is how the two end up
 * disagreeing.
 *
 * `processing` and `queued` are kept apart even though the old harness merged them into
 * one "in progress" pill. They mean different things to someone waiting: queued is
 * "no worker has picked this up", processing is "a worker has it". If a queue is
 * backed up, merging them is precisely the information that would have explained why.
 */
export function rollUpStats(stats: LibraryStats): StatsRollup {
  const rollup: StatsRollup = {
    total: 0,
    indexed: 0,
    failed: 0,
    queued: 0,
    processing: 0,
    active: 0,
  }

  DOCUMENT_CATEGORIES.forEach((category) => {
    const counts = stats.categories[category]

    /* A category the server stopped reporting would be undefined at runtime even
       though the type says otherwise, and one missing key should not take the whole
       overview down with a TypeError. */
    if (!counts) {
      return
    }

    rollup.total += counts.total
    rollup.indexed += counts.indexed
    rollup.failed += counts.failed
    rollup.queued += counts.queued
    rollup.processing += counts.parsing + counts.tagging + counts.embedding
  })

  rollup.active = rollup.queued + rollup.processing

  return rollup
}

/** Backend `GET /stages`. Lets the UI avoid hardcoding the pipeline. */
export interface StageOption {
  value: JobStage
  label: string
}

/* -------------------------------------------------------------------------- */
/* Requests                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The metadata that rides alongside a file on `POST /{category}/upload`.
 *
 * Every field is optional on the server, and blank is a meaningful value rather than a
 * gap: it hands the field to the tagger. Six of the seven are the tagger's own
 * `METADATA_FIELDS` — `doc_type, client, sector, service_line, geography, keywords` —
 * filled from the document text at Train time and then named in `auto_tagged_fields`,
 * which is what lets the UI mark a value as inferred rather than typed.
 *
 * `title` is the exception and does not behave like the other six. It is not one of
 * `METADATA_FIELDS`, so the tagger never touches it; a blank title is filled by
 * `_derive_title` from the parsed document instead, and that fill is *not* recorded in
 * `auto_tagged_fields`. So an auto-derived title is indistinguishable from a typed one
 * on the wire, and no badge should claim otherwise.
 *
 * Sent as multipart Form fields, not JSON, so `toUploadFormData` below is the only
 * thing that should build the body.
 */
export interface UploadMetadata {
  title: string
  client: string
  sector: string
  service_line: string
  geography: string
  /** Comma-separated on the wire; the form holds it as typed text. */
  keywords: string
  doc_type: string
}

export const EMPTY_UPLOAD_METADATA: UploadMetadata = {
  title: '',
  client: '',
  sector: '',
  service_line: '',
  geography: '',
  keywords: '',
  doc_type: '',
}

/**
 * Builds the multipart body.
 *
 * The seven names below are not a convention, they are the route's signature.
 * `POST /api/library/{category}/upload` declares `file: UploadFile = File(...)` and
 * seven `Form("")` parameters — `title, client, sector, service_line, geography,
 * keywords, doc_type`. A name that does not match one of those is not an error: the
 * parameter takes its `""` default and the value the uploader typed is dropped, with a
 * 201 and no complaint. That is the failure mode this function exists to prevent, so
 * the keys are pinned to `UploadMetadata` via `keyof` rather than written as loose
 * strings.
 *
 * Blank fields are omitted rather than sent as `""`, which is a smaller request and
 * nothing more — omitting is *equivalent* to sending `""` here, not different from it.
 * The default is `""`, the route calls `.strip()` on each one, and the tagger keys off
 * falsiness rather than presence: `library_indexing.py` builds `user_typed` from
 * `{key for key, value in user_supplied.items() if value}`, and `metadata.extract`
 * gates on `if not supplied.get(field_name)`. So a blank field asks the tagger to
 * infer a value whichever way it is sent, and the inferred field lands in
 * `auto_tagged_fields`. Trimming is the part that matters: `"  "` is truthy in JS and
 * would arrive as a value that the backend then strips to `""` anyway, so it is
 * trimmed here to keep both sides agreeing on what counts as blank.
 */
export function toUploadFormData(file: File, metadata: UploadMetadata): FormData {
  const body = new FormData()
  body.append('file', file)

  const fields: [keyof UploadMetadata, string][] = [
    ['title', metadata.title],
    ['client', metadata.client],
    ['sector', metadata.sector],
    ['service_line', metadata.service_line],
    ['geography', metadata.geography],
    ['keywords', metadata.keywords],
    ['doc_type', metadata.doc_type],
  ]

  fields.forEach(([name, value]) => {
    const trimmed = value.trim()
    if (trimmed) {
      body.append(name, trimmed)
    }
  })

  return body
}

/* -------------------------------------------------------------------------- */
/* Not on the wire                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Three things a document screen would like, and cannot have.
 *
 * There used to be a `ClientSideFields` interface here, and a `DocumentRecord =
 * LibraryDocument & ClientSideFields` that every screen rendered. It was a mistake, and
 * a specific kind of mistake worth naming: it let the pages be written against fields
 * the API does not return, so the only way to make them render at all was to feed them
 * fixtures. The screens looked finished and were structurally incapable of showing a
 * real library. The type is gone; the pages render `LibraryDocument`, and a column the
 * API cannot fill is not a column.
 *
 *   size_bytes         No size column on the `documents` table and no byte total on
 *                      `/stats`. The old harness only ever knew a file's size because
 *                      it kept `file.size` from the `File` object at upload time and
 *                      lost it on reload — see `PendingUpload` below, which is the only
 *                      honest place that number exists.
 *   uploaded_by_name   `DocumentOut` returns no uploader at all — not the id, not a
 *                      name. The column and the join both exist now:
 *                      `documents.uploaded_by` is a real `ForeignKey("users.id")` with a
 *                      `uploaded_by_user` relationship on the model. So this is one
 *                      field on a response schema away, not a schema-and-table change
 *                      like the other two. It is still not on the wire today, and a
 *                      type here must not pretend otherwise.
 *   summary            Nothing generates or stores one. `/ask` answers questions over
 *                      chunks; it does not summarise a document.
 *
 * `file_url` was the fourth entry and is no longer one. `GET /documents/{id}/file` serves
 * the stored upload, so the bytes are reachable and the viewer renders real pages. It is
 * still not a *field*, and there are two reasons rather than one. `file_path` stays
 * server-side and the id is the handle — that is why it is a route. And the route needs a
 * bearer token, so even as a string it would not be something a `<a href>` or an
 * `<img src>` could follow; `documentFileUrl` builds the path and
 * `fetchDocumentFileObjectUrl` is what actually produces a URL the browser will load.
 * A `file_url` field on this type would invite exactly the mistake that costs a 403.
 *
 * Adding any of the three above is a backend change. Until one lands, no type here
 * should pretend otherwise.
 */

/* -------------------------------------------------------------------------- */
/* Upload queue                                                               */
/* -------------------------------------------------------------------------- */

/**
 * A file sitting in the drop zone, before or after it has been sent.
 *
 * `status` tracks this one file's own journey, which is not the same thing as a
 * document's `training_status`: a file can fail to upload and so never become a
 * document at all. Keeping the two separate is what lets the upload list show a
 * duplicate rejection next to a successful send.
 */
export type PendingUploadStatus = 'ready' | 'uploading' | 'uploaded' | 'rejected'

export interface PendingUpload {
  /** Local id. The document's real UUID only exists once the upload succeeds. */
  id: string
  file: File
  status: PendingUploadStatus
  /** Set once uploaded — this is what `POST /train` is given. */
  documentId: string | null
  /** Why it was rejected, or the near-duplicate warning that came back with it. */
  message: string | null
  duplicateWarning: DuplicateCheckResult | null
}

/* -------------------------------------------------------------------------- */
/* Display helpers                                                            */
/* -------------------------------------------------------------------------- */

/**
 * What to call a document on screen.
 *
 * `title` is optional at upload and the tagger does not always fill it, so it can be
 * `""` on a perfectly valid row. Falling back to the filename is what the old harness
 * did and it is right: a blank cell tells the reader nothing, and the filename is at
 * least the thing they dragged in.
 */
export function documentTitle(document: LibraryDocument): string {
  return document.title.trim() || document.original_filename
}

/** The metadata fields the tagger can infer, in the order a reader scans them. */
export const METADATA_FIELDS = [
  'client',
  'sector',
  'service_line',
  'geography',
  'doc_type',
] as const

export type MetadataField = (typeof METADATA_FIELDS)[number]

export const METADATA_LABELS: Record<MetadataField, string> = {
  client: 'Client',
  sector: 'Sector',
  service_line: 'Service line',
  geography: 'Geography',
  doc_type: 'Type',
}

/** One metadata value, and whether a model supplied it rather than a person. */
export interface MetadataTag {
  field: MetadataField
  label: string
  value: string
  /** True when `auto_tagged_fields` names this field. */
  inferred: boolean
}

/**
 * The metadata worth showing, with inferred values marked.
 *
 * Blank fields are dropped rather than rendered as empty tags — the server stores `""`
 * for anything neither typed nor inferred, and a row of empty chips is worse than no
 * chips. The `inferred` flag is what draws the small "auto" marker, and it matters more
 * than it looks: a sector a person typed and a sector a model guessed carry very
 * different weight when someone is deciding whether to put this document in a bid.
 */
export function metadataTags(document: LibraryDocument): MetadataTag[] {
  const inferred = new Set(document.auto_tagged_fields)

  return METADATA_FIELDS.map((field) => ({
    field,
    label: METADATA_LABELS[field],
    value: document[field].trim(),
    inferred: inferred.has(field),
  })).filter((tag) => tag.value !== '')
}


/* -------------------------------------------------------------------------- */
/* Library search & grounded answers (LIB search / ask)                        */
/* -------------------------------------------------------------------------- */

/**
 * One retrieved passage — the wire shape of `SearchHit` in `schemas/library.py`.
 * The same object serves plain `/search` and the `sources` of `/ask`; `cited` is
 * only ever true on the ask path, where it marks a passage the generated answer
 * actually leaned on.
 */
export interface LibrarySearchHit {
  chunk_id: string
  document_id: string
  original_filename: string
  title: string
  category: DocumentCategory
  section_name: string
  phase: string
  page_number: number
  content: string
  similarity: number
  image_paths: string[]
  cited: boolean
}

/** `GET /api/library/search` — retrieval with no generation. */
export interface LibrarySearchResponse {
  query: string
  hits: LibrarySearchHit[]
}

/**
 * `POST /api/library/ask` — a grounded answer plus the passages it was built
 * from. `grounded` is false when the model declined for lack of evidence, cited
 * nothing, or generation was unavailable; the `sources` may still be worth
 * reading in every one of those cases, so they always travel with the answer.
 */
export interface LibraryAnswer {
  question: string
  answer: string
  grounded: boolean
  sources: LibrarySearchHit[]
}
