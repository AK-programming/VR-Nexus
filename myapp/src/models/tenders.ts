/**
 * Domain model for Tender Analysis — the wire types the tender endpoints speak,
 * and the small pure helpers the UI needs to reason about them.
 *
 * Mirrors `models/documents.ts` in shape and intent: `as const` arrays double as
 * the source of a union type *and* something iterable (no TS enums, because
 * `erasableSyntaxOnly` forbids them). Snake_case is kept on every field that
 * crosses the wire — these objects are deserialised straight from JSON and are
 * never reshaped in the service layer, so the names have to match the FastAPI
 * schema (`backend/app/schemas/tender.py`) exactly.
 *
 * The tender pipeline vocabulary is deliberately its OWN thing, separate from the
 * Evidence Library's job stages. A tender moves through nine ordered pipeline
 * stages and two terminal outcomes; a library document moves through five. They
 * look similar and are not, so they do not share types.
 */

/* -------------------------------------------------------------------------- */
/* Status                                                                     */
/* -------------------------------------------------------------------------- */

/**
 * Every status a tender row can hold, in pipeline order, matching
 * `TenderStatus` in the backend enums. The first nine are the ordered pipeline
 * steps `services/progress.py` counts through; `finalized` and `failed` are
 * terminal outcomes that sit past the last step rather than being steps.
 */
export const TENDER_STATUSES = [
  'uploaded',
  'parsing',
  'chunking',
  'extracting',
  'merging',
  'matching',
  'reporting',
  'assembling_folder',
  'ready_for_review',
  'finalized',
  'failed',
] as const

export type TenderStatus = (typeof TENDER_STATUSES)[number]

/**
 * The nine ordered pipeline stages, exactly as `PIPELINE_STAGES` in
 * `services/progress.py`. `finalized`/`failed` are intentionally absent — they
 * are outcomes, not stops on the rail, and the progress frame reports them as
 * "past the last step".
 */
export const PIPELINE_STAGES = [
  'uploaded',
  'parsing',
  'chunking',
  'extracting',
  'merging',
  'matching',
  'reporting',
  'assembling_folder',
  'ready_for_review',
] as const

export type PipelineStage = (typeof PIPELINE_STAGES)[number]

/** Short label for a status pill — the noun, not the gerund. */
export const TENDER_STATUS_LABELS: Record<TenderStatus, string> = {
  uploaded: 'Uploaded',
  parsing: 'Parsing',
  chunking: 'Chunking',
  extracting: 'Extracting',
  merging: 'Merging',
  matching: 'Matching',
  reporting: 'Reporting',
  assembling_folder: 'Assembling',
  ready_for_review: 'Ready for review',
  finalized: 'Finalized',
  failed: 'Failed',
}

/**
 * The longer phrase the progress stream shows against the active step. Matches
 * `STAGE_LABELS` in `services/progress.py` so a polled status and a streamed one
 * read identically.
 */
export const STAGE_LABELS: Record<PipelineStage, string> = {
  uploaded: 'Uploaded',
  parsing: 'Parsing document',
  chunking: 'Chunking',
  extracting: 'Extracting requirements',
  merging: 'Merging & de-duplicating',
  matching: 'Matching evidence',
  reporting: 'Generating report',
  assembling_folder: 'Assembling output folder',
  ready_for_review: 'Ready for review',
}

/** One-line description of what each stage is doing, for the processing timeline. */
export const STAGE_DESCRIPTIONS: Record<PipelineStage, string> = {
  uploaded: 'Your tender document has been received.',
  parsing: 'Reading the document and detecting its structure.',
  chunking: 'Splitting the tender into passages for analysis.',
  extracting: 'Identifying requirements, eligibility criteria and deadlines.',
  merging: 'Removing duplicates and consolidating requirements.',
  matching: 'Searching your evidence library for supporting documents.',
  reporting: 'Scoring coverage and building the compliance summary.',
  assembling_folder: 'Packaging the requirements matrix and output folder.',
  ready_for_review: 'Analysis complete — ready for your review.',
}

/**
 * Statuses that mean work is actively happening and the progress socket should
 * be live. `ready_for_review` is deliberately excluded: the pipeline has paused
 * for a human, so it is settled, not in flight.
 */
export const IN_FLIGHT_STATUSES: readonly TenderStatus[] = [
  'uploaded',
  'parsing',
  'chunking',
  'extracting',
  'merging',
  'matching',
  'reporting',
  'assembling_folder',
]

export function isInFlight(status: TenderStatus): boolean {
  return IN_FLIGHT_STATUSES.includes(status)
}

/**
 * Terminal for the *socket*: once a tender reaches one of these the progress
 * stream is closed by the server and will never send another frame. Note that
 * `ready_for_review` is NOT here — the socket stays open through review, and the
 * pipeline only truly ends at `finalized` (or `failed`).
 */
export function isSocketTerminal(status: TenderStatus): boolean {
  return status === 'finalized' || status === 'failed'
}

/**
 * "Settled" — the pipeline is no longer moving on its own, whether because it is
 * waiting for review, has been finalized, or has failed. The list UI stops the
 * live spinner treatment on any of these.
 */
export function isSettled(status: TenderStatus): boolean {
  return status === 'ready_for_review' || status === 'finalized' || status === 'failed'
}

/* -------------------------------------------------------------------------- */
/* Timeline stage states                                                      */
/* -------------------------------------------------------------------------- */

export type StageState = 'done' | 'active' | 'pending' | 'failed'

/**
 * Given the tender's current status, decide the state of every node on the
 * pipeline rail. Everything before the current stage is `done`, the current one
 * is `active` (except the terminal `ready_for_review`, which is itself `done`),
 * and everything after is `pending`.
 *
 * A failed tender colours every stage from where it broke onward as `failed`.
 * The break point is the last pipeline stage the tender was seen in; when that
 * is unknown we fail the whole rail from the first working step, which reads as
 * "this did not get through" rather than pretending a stage succeeded.
 */
export function stageStates(
  status: TenderStatus,
  failedAt?: PipelineStage,
): Record<PipelineStage, StageState> {
  const states = {} as Record<PipelineStage, StageState>

  if (status === 'failed') {
    const breakIndex = failedAt ? PIPELINE_STAGES.indexOf(failedAt) : 1
    PIPELINE_STAGES.forEach((stage, index) => {
      if (index < breakIndex) states[stage] = 'done'
      else states[stage] = 'failed'
    })
    return states
  }

  // finalized behaves like the rail is fully complete.
  const effective: PipelineStage =
    status === 'finalized' ? 'ready_for_review' : (status as PipelineStage)
  const currentIndex = PIPELINE_STAGES.indexOf(effective)

  PIPELINE_STAGES.forEach((stage, index) => {
    if (index < currentIndex) states[stage] = 'done'
    else if (index > currentIndex) states[stage] = 'pending'
    else states[stage] = stage === 'ready_for_review' ? 'done' : 'active'
  })
  return states
}

/* -------------------------------------------------------------------------- */
/* Requirements                                                               */
/* -------------------------------------------------------------------------- */

export const REQUIREMENT_STATUSES = [
  'extracted',
  'merged',
  'duplicate',
  'needs_manual_review',
] as const

export type RequirementStatus = (typeof REQUIREMENT_STATUSES)[number]

export const REQUIREMENT_STATUS_LABELS: Record<RequirementStatus, string> = {
  extracted: 'Extracted',
  merged: 'Merged',
  duplicate: 'Duplicate',
  needs_manual_review: 'Needs review',
}

export const EVALUATION_IMPACTS = ['pass_fail', 'technical', 'financial', 'compliance'] as const

export type EvaluationImpact = (typeof EVALUATION_IMPACTS)[number]

export const EVALUATION_IMPACT_LABELS: Record<EvaluationImpact, string> = {
  pass_fail: 'Pass / Fail',
  technical: 'Technical',
  financial: 'Financial',
  compliance: 'Compliance',
}

/** The three-way priority the UI shows, derived from `is_mandatory`. */
export type RequirementPriority = 'mandatory' | 'optional' | 'unspecified'

export function requirementPriority(isMandatory: boolean | null): RequirementPriority {
  if (isMandatory === true) return 'mandatory'
  if (isMandatory === false) return 'optional'
  return 'unspecified'
}

export const REQUIREMENT_PRIORITY_LABELS: Record<RequirementPriority, string> = {
  mandatory: 'Mandatory',
  optional: 'Optional',
  unspecified: 'Unspecified',
}

/* -------------------------------------------------------------------------- */
/* Evidence matches                                                           */
/* -------------------------------------------------------------------------- */

/**
 * How strongly a library document was matched to a requirement. Mirrors
 * `MatchType`: `auto` ≥ 0.85, `suggested` 0.50–0.84, `missing` < 0.50 (no
 * usable evidence found).
 */
export const MATCH_TYPES = ['auto', 'suggested', 'missing'] as const

export type MatchType = (typeof MATCH_TYPES)[number]

export const MATCH_TYPE_LABELS: Record<MatchType, string> = {
  auto: 'Auto-matched',
  suggested: 'Suggested',
  missing: 'No evidence',
}

/** The reviewer's decision on a match. */
export const MATCH_REVIEW_STATUSES = ['pending', 'accepted', 'rejected', 'reassigned'] as const

export type MatchReviewStatus = (typeof MATCH_REVIEW_STATUSES)[number]

export const MATCH_REVIEW_STATUS_LABELS: Record<MatchReviewStatus, string> = {
  pending: 'Pending review',
  accepted: 'Accepted',
  rejected: 'Rejected',
  reassigned: 'Reassigned',
}

/** The action body for reviewing a match. `document_id` is only read for `reassign`. */
export type MatchReviewAction = 'accept' | 'reject' | 'reassign'

export interface MatchReviewUpdate {
  action: MatchReviewAction
  document_id?: string
}

/* -------------------------------------------------------------------------- */
/* Wire types — one per FastAPI schema                                        */
/* -------------------------------------------------------------------------- */

/** POST /api/tenders — returned immediately, before any processing. */
export interface TenderUploadResponse {
  id: string
  name: string
  original_filename: string
  status: TenderStatus
  progress_percent: number
  page_count: number | null
  created_at: string
}

/** One row of GET /api/tenders. */
export interface TenderListItem {
  id: string
  name: string
  original_filename: string
  status: TenderStatus
  progress_percent: number
  extracted_requirements_count: number
  page_count: number | null
  issuing_authority: string | null
  submission_deadline: string | null
  finalized_at: string | null
  created_at: string
}

/** GET /api/tenders/{id} — full detail. */
export interface TenderDetail {
  id: string
  name: string
  original_filename: string
  page_count: number | null
  file_size_bytes: number | null
  status: TenderStatus
  progress_percent: number
  progress_message: string | null
  extracted_requirements_count: number

  reference_id: string | null
  issuing_authority: string | null
  sector: string | null
  location: string | null
  tender_value: number | null
  submission_deadline: string | null

  evaluation_weighting: Record<string, unknown> | null
  total_marks_available: number | null
  total_marks_captured: number | null

  has_output: boolean
  finalized_at: string | null
  created_at: string
  updated_at: string | null
}

/** PATCH /api/tenders/{id} — every field optional; only those sent are applied. */
export interface TenderUpdate {
  name?: string
  reference_id?: string | null
  issuing_authority?: string | null
  sector?: string | null
  location?: string | null
  tender_value?: number | null
  submission_deadline?: string | null
  evaluation_weighting?: Record<string, unknown> | null
}

/** One extracted requirement (GET /api/tenders/{id}/requirements). */
export interface Requirement {
  id: string
  tender_id: string
  page_number: number | null
  section_name: string | null
  clause_reference: string | null
  description: string
  is_mandatory: boolean | null
  evaluation_impact: EvaluationImpact | null
  marks: number | null
  evidence_required: boolean
  evidence_description: string | null
  responsibility: string | null
  status: RequirementStatus
  needs_manual_review: boolean
  remarks: string | null
  match_count: number
  best_match_type: MatchType | null
  created_at: string
}

/** One evidence match, flattened across requirement + document + match. */
export interface EvidenceMatch {
  id: string
  requirement_id: string
  requirement_clause: string | null
  requirement_description: string
  document_id: string
  document_title: string | null
  document_filename: string | null
  document_category: string | null
  confidence_score: number | null
  match_type: MatchType
  review_status: MatchReviewStatus
  reviewed_at: string | null
  created_at: string
}

/** One row of the report's per-evaluation-impact breakdown. */
export interface ImpactBreakdown {
  impact: string
  requirement_count: number
  marks_available: number
  marks_captured: number
}

/** GET /api/tenders/{id}/report — computed live, never persisted. */
export interface TenderReport {
  tender_id: string
  requirements_total: number
  mandatory_count: number
  optional_count: number
  unspecified_count: number

  marks_available: number
  marks_captured: number
  coverage_percent: number

  auto_matches: number
  suggested_matches: number
  missing_matches: number
  accepted_matches: number
  rejected_matches: number
  pending_matches: number

  requirements_with_evidence: number
  requirements_without_evidence: number

  by_evaluation_impact: ImpactBreakdown[]
  evaluation_weighting: Record<string, unknown> | null
}

/** One chunk of the parsed tender (only surfaced if a debug view needs it). */
export interface TenderChunk {
  chunk_index: number
  section: string
  page_start: number
  page_end: number
  token_count: number
  overlap_tokens: number
}

/* -------------------------------------------------------------------------- */
/* Progress                                                                   */
/* -------------------------------------------------------------------------- */

/**
 * The raw frame the tender progress socket sends (and what
 * `get_latest_progress` stores). Shape fixed by `publish_progress` in
 * `services/progress.py`. Note this is NOT the library `ProgressEvent` shape.
 */
export interface TenderProgressFrame {
  tender_id: string
  status: TenderStatus
  step_label: string
  current_step: number
  total_steps: number
  percent_complete: number
  message: string | null
  extracted_requirements_count: number | null
  updated_at: string
}

/**
 * The normalised progress the hook exposes, whether it came from a live socket
 * frame or a fallback poll of GET /{id}. One shape so the UI never has to know
 * which transport produced it.
 */
export interface TenderProgress {
  status: TenderStatus
  stepLabel: string
  currentStep: number
  totalSteps: number
  percent: number
  message: string | null
  extractedRequirementsCount: number | null
  updatedAt: string | null
}

/** Normalise a live socket frame into the shape the UI reads. */
export function progressFromFrame(frame: TenderProgressFrame): TenderProgress {
  return {
    status: frame.status,
    stepLabel: frame.step_label,
    currentStep: frame.current_step,
    totalSteps: frame.total_steps,
    percent: frame.percent_complete,
    message: frame.message,
    extractedRequirementsCount: frame.extracted_requirements_count,
    updatedAt: frame.updated_at,
  }
}

/**
 * Normalise a polled tender detail into the same progress shape. The poll has no
 * step label or step index, so those are derived from the status's position in
 * the pipeline.
 */
export function progressFromDetail(tender: {
  status: TenderStatus
  progress_percent: number
  progress_message: string | null
  extracted_requirements_count: number
  updated_at?: string | null
}): TenderProgress {
  const stageIndex = PIPELINE_STAGES.indexOf(tender.status as PipelineStage)
  const currentStep = stageIndex >= 0 ? stageIndex + 1 : PIPELINE_STAGES.length
  const stepLabel =
    stageIndex >= 0 ? STAGE_LABELS[tender.status as PipelineStage] : TENDER_STATUS_LABELS[tender.status]
  return {
    status: tender.status,
    stepLabel,
    currentStep,
    totalSteps: PIPELINE_STAGES.length,
    percent: tender.progress_percent,
    message: tender.progress_message,
    extractedRequirementsCount: tender.extracted_requirements_count,
    updatedAt: tender.updated_at ?? null,
  }
}

/* -------------------------------------------------------------------------- */
/* Upload                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * A tender is a single formal PDF. The server (`validate_tender_upload`) rejects
 * anything whose name does not end in `.pdf` with a 400, and the pipeline reads
 * pages with PyMuPDF, so the dropzone accepts PDF only — the design mock's
 * "PDF/DOCX" label is aspirational, and offering DOCX here would only earn a
 * server rejection after the upload. This is narrower than the Evidence Library
 * (which also takes DOCX/PPTX/images), so it has its own accept map.
 */
export const TENDER_DROPZONE_ACCEPT: Record<string, string[]> = {
  'application/pdf': ['.pdf'],
}

export const TENDER_ACCEPTED_EXTENSIONS = 'PDF'
export const TENDER_MAX_UPLOAD_MB = 100
export const TENDER_MAX_UPLOAD_BYTES = TENDER_MAX_UPLOAD_MB * 1024 * 1024

/**
 * The metadata form on the upload screen. Every field is optional — the server
 * defaults `name` to the filename and the PARSING stage fills the rest in from
 * the tender itself — so a blank form is a valid upload. The field set is exactly
 * the writable surface of `PATCH /api/tenders/{id}` (`TenderUpdate`): there is no
 * `description` here because the server has no column to store one, and an input
 * that maps to nothing would be a control that silently does nothing.
 *
 * All values are strings because they come straight off form inputs; the upload
 * flow coerces `tender_value` to a number and drops the empties before PATCHing.
 */
export interface TenderUploadMetadata {
  name: string
  reference_id: string
  issuing_authority: string
  sector: string
  location: string
  tender_value: string
  submission_deadline: string
}

export const EMPTY_TENDER_METADATA: TenderUploadMetadata = {
  name: '',
  reference_id: '',
  issuing_authority: '',
  sector: '',
  location: '',
  tender_value: '',
  submission_deadline: '',
}

/* -------------------------------------------------------------------------- */
/* Small display helpers                                                       */
/* -------------------------------------------------------------------------- */

/** The name to show for a tender, falling back to its original filename. */
export function tenderTitle(tender: { name?: string | null; original_filename: string }): string {
  const name = (tender.name ?? '').trim()
  return name || tender.original_filename
}

/**
 * A rough "is this tender worth reviewing yet" gate the list uses to enable the
 * Open Analysis affordance without a second request: anything that has extracted
 * requirements, or has settled.
 */
export function hasReviewableAnalysis(tender: {
  status: TenderStatus
  extracted_requirements_count: number
}): boolean {
  return isSettled(tender.status) || tender.extracted_requirements_count > 0
}
