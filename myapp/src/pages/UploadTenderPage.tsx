/**
 * Adding a tender for analysis.
 *
 * A sibling of the documents `UploadDocumentsPage`, and it shares that screen's
 * paint and its optional-metadata idiom — but the flow underneath is genuinely
 * simpler, and the differences are all consequences of how the tender backend
 * works rather than styling choices:
 *
 *   **One file, always.** A tender is one formal PDF, so this drives a single-file
 *   `TenderDropzone` (`onFileAccepted`) rather than the library's batch dropzone.
 *   There is no queue, no per-row status list — one document, one row.
 *
 *   **No category step.** The library splits its uploads across three endpoints by
 *   category, so that choice comes first there. A tender has no such split — the
 *   section is the category — so the first and only thing to choose is the file.
 *
 *   **One press, not two.** The library separates upload from indexing because a
 *   near-duplicate warning is a judgement a person makes before paying to embed.
 *   `POST /api/tenders` has no such gate: it stores the file *and* enqueues the
 *   whole pipeline in one call, returning in milliseconds. So there is nothing to
 *   "start" on a second press — the page's job ends by handing off to the live
 *   Processing view, exactly where the pipeline it just kicked off is watched.
 *
 *   **Metadata is a follow-up, and optional in the truest sense.** The upload
 *   endpoint takes the file and nothing else, so any details the user fills in are
 *   applied by a second `PATCH /api/tenders/{id}` once the row exists. The PARSING
 *   stage reads reference, authority, deadline and the rest out of the tender
 *   itself, so a blank field is a request to infer rather than a gap — and a blank
 *   form is a perfectly valid upload. `buildPatch` sends only the fields that were
 *   actually typed, so an untouched field never overwrites what the pipeline finds.
 *
 *   **A failed PATCH does not undo the upload.** By the time the metadata call runs
 *   the tender is already created and analysing, so a failure there is recoverable,
 *   not a dead end: the page keeps the created id and offers to retry the details or
 *   skip straight to Processing. It never silently drops what was typed, and never
 *   reports a save that did not happen.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import {
  EMPTY_TENDER_METADATA,
  TENDER_ACCEPTED_EXTENSIONS,
  TENDER_MAX_UPLOAD_MB,
} from '@/models/tenders'
import type { TenderUpdate, TenderUploadMetadata } from '@/models/tenders'
import { updateTender, uploadTender } from '@/services/tenderService'
import { errorMessage } from '@/lib/apiClient'
import { formatBytes } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import type { AlertTone } from '@/components/feedback/AlertMessage'
import { TenderDropzone } from '@/components/tender/TenderDropzone'
import { FileGlyph } from '@/components/documents/FileGlyph'
import {
  ArrowRightIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  SpinnerIcon,
  TrashIcon,
  UploadIcon,
} from '@/components/ui/icons'

/** Same paint as the library's upload fields, so the two screens share one field style. */
const FIELD_CLASSES = [
  'h-10 w-full rounded-xl border border-hairline bg-field px-3 text-sm text-neutral-900',
  'transition-colors duration-150 placeholder:text-neutral-400 hover:border-neutral-300',
  'focus:border-brand-400 focus:bg-surface',
].join(' ')

/**
 * The subset of metadata the server can store, coerced and emptied-out for the PATCH.
 *
 * Only fields that were actually typed are included: an untouched field is left out
 * entirely so it never overwrites what the PARSING stage infers from the tender. The
 * value is coerced to a number here because `tender_value` is a `Numeric` column —
 * everything else is a string the server accepts as-is (a `date` input already emits
 * the `YYYY-MM-DD` the deadline column wants).
 */
function buildPatch(metadata: TenderUploadMetadata): TenderUpdate {
  const patch: TenderUpdate = {}

  const name = metadata.name.trim()
  if (name) patch.name = name

  const reference = metadata.reference_id.trim()
  if (reference) patch.reference_id = reference

  const authority = metadata.issuing_authority.trim()
  if (authority) patch.issuing_authority = authority

  const sector = metadata.sector.trim()
  if (sector) patch.sector = sector

  const location = metadata.location.trim()
  if (location) patch.location = location

  const value = metadata.tender_value.trim()
  if (value) {
    const parsed = Number(value)
    if (Number.isFinite(parsed) && parsed >= 0) patch.tender_value = parsed
  }

  const deadline = metadata.submission_deadline.trim()
  if (deadline) patch.submission_deadline = deadline

  return patch
}

/**
 * The one thing worth checking before sending: a value that was typed but is not a
 * positive number. `type="number"` stops most bad input at the field, but a pasted
 * "-5" would otherwise be silently dropped by `buildPatch` — better to say why.
 */
function metadataError(metadata: TenderUploadMetadata): string | null {
  const value = metadata.tender_value.trim()
  if (value) {
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || parsed < 0) {
      return 'Tender value must be a positive amount, or left blank.'
    }
  }
  return null
}

/** One metadata input. See `UploadDocumentsPage`'s note on why this is not `TextField`. */
function MetadataField({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
  type = 'text',
  min,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  hint?: string
  type?: 'text' | 'number' | 'date'
  min?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-neutral-700">
        {label}
      </label>
      <input
        id={id}
        type={type}
        min={min}
        inputMode={type === 'number' ? 'decimal' : undefined}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`mt-1.5 ${FIELD_CLASSES}`}
      />
      {hint ? <p className="mt-1.5 text-xs text-neutral-500">{hint}</p> : null}
    </div>
  )
}

/** The wording and glyph for where the single file has got to. */
function FileStatusMark({ state }: { state: 'ready' | 'uploading' | 'saving' | 'uploaded' }) {
  if (state === 'uploading') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-800">
        <SpinnerIcon className="size-3.5 animate-spin" />
        Sending
      </span>
    )
  }

  if (state === 'saving') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-800">
        <SpinnerIcon className="size-3.5 animate-spin" />
        Saving details
      </span>
    )
  }

  if (state === 'uploaded') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-800">
        <CheckCircleIcon className="size-3.5" />
        Uploaded
      </span>
    )
  }

  return <span className="text-xs font-medium text-neutral-500">Ready</span>
}

export function UploadTenderPage() {
  const navigate = useNavigate()

  const [file, setFile] = useState<File | null>(null)
  const [metadata, setMetadata] = useState<TenderUploadMetadata>(EMPTY_TENDER_METADATA)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ tone: AlertTone; text: string } | null>(null)

  /* Set once the upload has succeeded. Its presence is what tells the flow the file is
     already on the server: a details-retry reuses this id rather than re-uploading. */
  const [createdId, setCreatedId] = useState<string | null>(null)
  const uploaded = createdId !== null

  const fileState: 'ready' | 'uploading' | 'saving' | 'uploaded' = busy
    ? uploaded
      ? 'saving'
      : 'uploading'
    : uploaded
      ? 'uploaded'
      : 'ready'

  function setField(name: keyof TenderUploadMetadata, value: string) {
    setMetadata((current) => ({ ...current, [name]: value }))
  }

  function handleFileAccepted(next: File) {
    setNotice(null)
    setFile(next)
  }

  function clearFile() {
    setFile(null)
    setNotice(null)
  }

  async function handleSubmit() {
    const invalid = metadataError(metadata)
    if (invalid) {
      setNotice({ tone: 'error', text: invalid })
      return
    }

    setBusy(true)
    setNotice(null)

    /* Create the tender once. On a details-retry the row already exists (createdId is
       set), so reuse it rather than uploading the same file a second time. */
    let id = createdId
    if (id === null) {
      if (!file) {
        setBusy(false)
        return
      }

      try {
        const created = await uploadTender(file)
        id = created.id
        setCreatedId(created.id)
      } catch (error) {
        setNotice({ tone: 'error', text: errorMessage(error) })
        setBusy(false)
        return
      }
    }

    /* Apply the optional metadata. The pipeline is already running, so a failure here
       does not undo the upload — it is a note to carry forward, not a reason to hold
       the user on a form for a tender that is already being read. The message travels
       in navigation state and the processing page shows it once. */
    const patch = buildPatch(metadata)
    let warning: string | null = null

    if (Object.keys(patch).length > 0) {
      try {
        await updateTender(id, patch)
      } catch (error) {
        warning = `The tender was uploaded and is being analysed, but its details did not save (${errorMessage(
          error,
        )}). Add them later from the tender's page.`
      }
    }

    /* Straight to the progress screen, always: the analysis started the moment the
       upload landed, so the only thing left to do with this tender is watch it. */
    navigate(`${ROUTES.tenderProcessing}?tender=${id}`, {
      state: warning ? { notice: warning } : undefined,
    })
  }

  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <Panel
          title="Tender document"
          description={
            uploaded
              ? 'Uploaded and analysing.'
              : file
                ? `Ready to upload · ${formatBytes(file.size)}`
                : `A single ${TENDER_ACCEPTED_EXTENSIONS}, up to ${TENDER_MAX_UPLOAD_MB} MB. VR-Nexus reads it clause by clause.`
          }
        >
          <div className="flex flex-col gap-4">
            <TenderDropzone
              onFileAccepted={handleFileAccepted}
              disabled={busy || uploaded}
              hint={
                uploaded
                  ? 'This tender has been uploaded.'
                  : file
                    ? 'Drop a different PDF to replace it.'
                    : undefined
              }
            />

            {file ? (
              <div className="flex items-start gap-3 rounded-xl border border-hairline bg-surface px-3.5 py-3">
                <FileGlyph filename={file.name} />

                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-neutral-900">{file.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500">
                    <span className="tabular-nums">{formatBytes(file.size)}</span>
                    <span aria-hidden="true">·</span>
                    <FileStatusMark state={fileState} />
                  </p>
                </div>

                {/* No removing the file once it is on the server — the row is a record of
                    what was uploaded at that point, not a still-editable queue. */}
                {!uploaded ? (
                  <IconAction
                    label={`Remove ${file.name}`}
                    icon={<TrashIcon />}
                    tone="danger"
                    disabled={busy}
                    onClick={clearFile}
                  />
                ) : null}
              </div>
            ) : null}

            {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              {/* After a metadata failure the tender is already analysing, so skipping is
                  a real, safe way forward rather than an abandon. */}
              {uploaded ? (
                <ActionButton
                  variant="secondary"
                  to={`${ROUTES.tenderProcessing}?tender=${createdId}`}
                >
                  Skip for now
                </ActionButton>
              ) : null}

              <ActionButton
                variant="primary"
                leadingIcon={uploaded ? undefined : <UploadIcon />}
                trailingIcon={uploaded ? <ArrowRightIcon /> : undefined}
                disabled={busy || (!uploaded && !file)}
                onClick={() => void handleSubmit()}
              >
                {uploaded ? 'Save details & continue' : 'Upload & analyse'}
              </ActionButton>
            </div>
          </div>
        </Panel>
      </div>

      {/*
        Details sit beside the flow from `xl` and below it on anything narrower, matching
        their importance: helpful, never required. The disclosure starts closed so the
        default path is drop-and-send, and opening it is the deliberate act of overriding
        what the pipeline would otherwise infer from the tender.
      */}
      <div className="w-full xl:max-w-sm">
        <Panel
          title="Details"
          description="Leave anything blank and VR-Nexus fills it in while reading the tender."
          action={
            <button
              type="button"
              onClick={() => setDetailsOpen((open) => !open)}
              aria-expanded={detailsOpen}
              aria-controls="tender-details"
              className="inline-flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-sm font-medium text-brand-600 transition-colors hover:text-brand-700"
            >
              {detailsOpen ? 'Hide' : 'Add details'}
              <ChevronDownIcon
                className={[
                  'size-4 transition-transform duration-200',
                  detailsOpen ? 'rotate-180' : '',
                ].join(' ')}
              />
            </button>
          }
        >
          {detailsOpen ? (
            <div id="tender-details" className="flex flex-col gap-4">
              <MetadataField
                id="tender-name"
                label="Name"
                value={metadata.name}
                onChange={(value) => setField('name', value)}
                placeholder="Supply & Installation of Network Infrastructure"
                hint="How the tender is named in VR-Nexus, rather than its filename."
              />
              <MetadataField
                id="tender-reference"
                label="Reference"
                value={metadata.reference_id}
                onChange={(value) => setField('reference_id', value)}
                placeholder="PPRA-2026-IT-0042"
                hint="The tender reference or notice number."
              />
              <MetadataField
                id="tender-authority"
                label="Issuing authority"
                value={metadata.issuing_authority}
                onChange={(value) => setField('issuing_authority', value)}
                placeholder="National Highway Authority"
              />
              <MetadataField
                id="tender-sector"
                label="Sector"
                value={metadata.sector}
                onChange={(value) => setField('sector', value)}
                placeholder="Information Technology"
              />
              <MetadataField
                id="tender-location"
                label="Location"
                value={metadata.location}
                onChange={(value) => setField('location', value)}
                placeholder="Islamabad"
              />
              <MetadataField
                id="tender-value"
                label="Tender value"
                value={metadata.tender_value}
                onChange={(value) => setField('tender_value', value)}
                placeholder="50000000"
                type="number"
                min="0"
                hint="Estimated value in PKR."
              />
              <MetadataField
                id="tender-deadline"
                label="Submission deadline"
                value={metadata.submission_deadline}
                onChange={(value) => setField('submission_deadline', value)}
                type="date"
                hint="The bid submission deadline."
              />
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-neutral-500">
              Reference, authority, sector, location, value and deadline are all read from
              the tender itself. Fill them in only where you want to overrule that.
            </p>
          )}
        </Panel>
      </div>
    </div>
  )
}
