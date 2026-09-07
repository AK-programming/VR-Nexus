/**
 * Adding documents to the library.
 *
 * Three steps, in the order the API enforces them, and the page is laid out to match:
 * pick a category, add files, send them. Category is first because it is not metadata —
 * it is part of the URL (`POST /{category}/upload`), so nothing can be sent without it.
 *
 * **Upload continues into indexing on its own** — one press takes a clean batch from
 * files on disk to the processing page watching the job. The server still splits the
 * two calls, and the reason it does is preserved as the one exception: the duplicate
 * check runs at upload, before anything is parsed or embedded, and a near-duplicate
 * warning is a judgement for a person to make. So a batch that came back with a
 * warning — or with any refusal — stops here with the Index button, rather than
 * discovering "this is 96% the same as a document you already have" after paying to
 * embed it. Everything else goes straight through.
 *
 * Metadata is optional in the truest sense — the backend's tagger fills in whatever is
 * left blank and records what it inferred under `auto_tagged_fields`, so a blank field
 * is a request rather than a gap. `toUploadFormData` omits empty values instead of
 * sending `""`, which is what keeps that distinction intact.
 *
 * `title` only appears when exactly one file is queued. Every other field can sensibly
 * describe a batch — five case studies from one client, one sector, one geography — but
 * a title cannot, and applying one title to four documents would name them all the same
 * thing.
 */

import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import {
  CATEGORY_LABELS,
  DOCUMENT_CATEGORIES,
  EMPTY_UPLOAD_METADATA,
  fileTypeFromName,
} from '@/models/documents'
import type {
  DocumentCategory,
  PendingUpload,
  UploadMetadata,
} from '@/models/documents'
import { train, uploadDocument } from '@/services/documentService'
import { ApiError, errorMessage } from '@/lib/apiClient'
import { formatBytes, formatCount } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton, IconAction } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { DocumentDropzone } from '@/components/documents/DocumentDropzone'
import { FileGlyph } from '@/components/documents/FileGlyph'
import {
  AlertTriangleIcon,
  BarChartIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  DatabaseIcon,
  FileTextIcon,
  ShieldCheckIcon,
  SpinnerIcon,
  TrashIcon,
  UploadIcon,
  XCircleIcon,
} from '@/components/ui/icons'

/** What each category is for, so the choice is not three synonyms for "document". */
const CATEGORY_HELP: Record<DocumentCategory, string> = {
  case_study: 'Past project write-ups. What VR-Nexus cites as proven experience.',
  methodology: 'How the work gets done - delivery, QA, security, governance.',
  company_document: 'Profiles, certifications, policies and other standing material.',
}

const CATEGORY_ICONS: Record<DocumentCategory, ReactNode> = {
  case_study: <BarChartIcon className="size-4.5" />,
  methodology: <DatabaseIcon className="size-4.5" />,
  company_document: <ShieldCheckIcon className="size-4.5" />,
}

/** Same paint as the library's filter controls, so the module has one field style. */
const FIELD_CLASSES = [
  'h-10 w-full rounded-xl border border-hairline bg-field px-3 text-sm text-neutral-900',
  'transition-colors duration-150 placeholder:text-neutral-400 hover:border-neutral-300',
  'focus:border-brand-400 focus:bg-surface',
].join(' ')

/**
 * One metadata input.
 *
 * Not `TextField`: that component carries a tinted icon plate designed for a 44px auth
 * field with one field per row, and seven of them in a two-column grid is seven red
 * plates competing for attention in a form whose entire point is that it is optional.
 * Same reasoning as `DataTable`'s own checkbox — shared paint, different job.
 */
function MetadataField({
  id,
  label,
  value,
  onChange,
  placeholder,
  hint,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder: string
  hint?: string
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-neutral-700">
        {label}
      </label>
      <input
        id={id}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`mt-1.5 ${FIELD_CLASSES}`}
      />
      {hint ? <p className="mt-1.5 text-xs text-neutral-500">{hint}</p> : null}
    </div>
  )
}

/** The glyph and wording for each state of a queued file. */
function PendingStatusMark({ upload }: { upload: PendingUpload }) {
  if (upload.status === 'uploading') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-sky-800 dark:text-sky-300">
        <SpinnerIcon className="size-3.5 animate-spin" />
        Sending
      </span>
    )
  }

  if (upload.status === 'uploaded') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-800 dark:text-emerald-300">
        <CheckCircleIcon className="size-3.5" />
        Uploaded
      </span>
    )
  }

  if (upload.status === 'rejected') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-rose-800 dark:text-rose-300">
        <XCircleIcon className="size-3.5" />
        Not accepted
      </span>
    )
  }

  return <span className="text-xs font-medium text-neutral-500">Ready</span>
}

export function UploadDocumentsPage() {
  const navigate = useNavigate()

  const [category, setCategory] = useState<DocumentCategory>('case_study')
  const [pending, setPending] = useState<PendingUpload[]>([])
  const [metadata, setMetadata] = useState<UploadMetadata>(EMPTY_UPLOAD_METADATA)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ tone: 'error' | 'success'; text: string } | null>(null)

  const readyCount = pending.filter((upload) => upload.status === 'ready').length

  /* `flatMap` rather than `filter().map()`: a filter does not narrow `documentId` from
     `string | null`, so the pair would need a cast to compile. This needs none. */
  const uploadedIds = useMemo(
    () =>
      pending.flatMap((upload) =>
        upload.status === 'uploaded' && upload.documentId ? [upload.documentId] : [],
      ),
    [pending],
  )

  const totalBytes = pending.reduce((sum, upload) => sum + upload.file.size, 0)

  function setField(name: keyof UploadMetadata, value: string) {
    setMetadata((current) => ({ ...current, [name]: value }))
  }

  function handleFilesAccepted(files: File[]) {
    setNotice(null)

    setPending((current) => {
      /* Same name and same size twice is the accidental double-drop, not two documents.
         Filtered here rather than on send, so the list never shows a duplicate row a
         person then has to work out how to remove. */
      const seen = new Set(current.map((upload) => `${upload.file.name}:${upload.file.size}`))

      const additions = files
        .filter((file) => !seen.has(`${file.name}:${file.size}`))
        .map<PendingUpload>((file) => ({
          /* A local id only. The document's real UUID does not exist until the upload
             succeeds, and reusing the filename as a key breaks the moment two folders
             both contain "Company Profile.pdf". */
          id: crypto.randomUUID(),
          file,
          status: 'ready',
          documentId: null,
          message: null,
          duplicateWarning: null,
        }))

      return [...current, ...additions]
    })
  }

  function removeUpload(id: string) {
    setPending((current) => current.filter((upload) => upload.id !== id))
  }

  function patchUpload(id: string, patch: Partial<PendingUpload>) {
    setPending((current) =>
      current.map((upload) => (upload.id === id ? { ...upload, ...patch } : upload)),
    )
  }

  async function handleUpload() {
    const queue = pending.filter((upload) => upload.status === 'ready')

    if (queue.length === 0) {
      return
    }

    setBusy(true)
    setNotice(null)

    /* Only send a title when a single file is queued. With several, the field is not
       even rendered — but a title typed before a second file was added would otherwise
       still be sitting in state, and would name every document in the batch the same. */
    const payload: UploadMetadata =
      queue.length === 1 ? metadata : { ...metadata, title: '' }

    let succeeded = 0
    let failed = 0
    /* Collected here rather than read from `uploadedIds` afterwards: `patchUpload` is a
       state update, so the derived list is still the pre-upload one inside this call. */
    const uploadedNow: string[] = []
    /* Near-duplicates are uploaded, not refused — but they are the one case the
       automatic hand-off to indexing must not swallow (see the file header). */
    let flagged = 0

    /* One at a time. Six parallel multipart uploads of a 100 MB file each is a way to
       exhaust the browser's connection pool and time all six out together; sequential
       uploads also let each row report its own outcome as it happens. */
    for (const upload of queue) {
      patchUpload(upload.id, { status: 'uploading', message: null })

      try {
        const response = await uploadDocument(category, upload.file, payload)

        patchUpload(upload.id, {
          status: 'uploaded',
          documentId: response.document.id,
          duplicateWarning: response.duplicate_warning,
          message:
            response.duplicate_warning && response.duplicate_warning.near_matches.length > 0
              ? `Similar to ${response.duplicate_warning.near_matches[0].original_filename}. Uploaded anyway - check before indexing.`
              : null,
        })
        uploadedNow.push(response.document.id)
        succeeded += 1

        if (response.duplicate_warning && response.duplicate_warning.near_matches.length > 0) {
          flagged += 1
        }
      } catch (error) {
        /* 409 is the byte-identical duplicate, which the server refuses outright. It is
           the one failure that is not a problem to fix, so it gets its own wording
           rather than the generic message. */
        const isDuplicate = error instanceof ApiError && error.status === 409

        patchUpload(upload.id, {
          status: 'rejected',
          message: isDuplicate
            ? 'Already in the library - an identical file is stored.'
            : errorMessage(error),
        })
        failed += 1
      }
    }

    setBusy(false)

    /* A clean batch continues on its own: indexing is the only thing an uploaded
       document is waiting for, and stopping to ask for a second click on the one
       button that could possibly be pressed is a step that carries no decision. The
       user lands on the processing page watching the job they just started. A batch
       with refusals stops here instead — those rows need reading before anything is
       indexed, so the manual Index button stays for that case. */
    if (failed === 0 && flagged === 0 && uploadedNow.length > 0) {
      await startIndexing(uploadedNow)
      return
    }

    if (failed === 0) {
      setNotice({
        tone: 'success',
        text: `${formatCount(succeeded)} uploaded, but ${
          flagged === 1 ? 'one looks' : `${formatCount(flagged)} look`
        } similar to something already in the library. Check the note below, then index when you are happy.`,
      })
      return
    }

    setNotice({
      tone: 'error',
      text:
        succeeded === 0
          ? 'Nothing was uploaded. Each file below says why.'
          : `${formatCount(succeeded)} uploaded, ${formatCount(failed)} refused. Each refused file says why.`,
    })
  }

  /**
   * Enqueues indexing for the given documents and follows the first job to the
   * processing page. Takes its ids as an argument rather than reading `uploadedIds`
   * so the automatic path (straight after a clean upload, when that derived list has
   * not re-rendered yet) and the manual button can share one implementation.
   */
  async function startIndexing(ids: string[]) {
    if (ids.length === 0) {
      return
    }

    setBusy(true)
    setNotice(null)

    try {
      const response = await train(ids)
      const firstJob = response.jobs[0]

      if (firstJob) {
        navigate(`${ROUTES.documentsProcessing}?job=${firstJob.id}`)
        return
      }

      setNotice({
        tone: 'success',
        text: 'Those documents are already indexed or in progress.',
      })
    } catch (error) {
      setNotice({ tone: 'error', text: errorMessage(error) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
        {/*
          Radio cards, not a select. Three options, each needing a sentence of
          explanation, and the choice changes which endpoint the file goes to — that is
          worth the vertical space. A native fieldset carries the grouping, so arrow
          keys move between them the way a keyboard user expects.
        */}
        <Panel
          title="Category"
          description="Where this belongs in the library. It decides how VR-Nexus cites the document."
        >
          <fieldset>
            <legend className="sr-only">Document category</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {DOCUMENT_CATEGORIES.map((value) => {
                const isActive = category === value

                return (
                  <label
                    key={value}
                    className={[
                      'group relative flex cursor-pointer flex-col gap-2 rounded-xl border p-4',
                      'transition-colors duration-150',
                      isActive
                        ? 'border-brand-400 bg-selected'
                        : 'border-hairline bg-surface hover:border-neutral-300 hover:bg-surface-muted',
                    ].join(' ')}
                  >
                    <input
                      type="radio"
                      name="category"
                      value={value}
                      checked={isActive}
                      onChange={() => setCategory(value)}
                      className="peer sr-only"
                    />
                    {/* The focus ring lands on the card rather than the hidden input,
                        so keyboard focus is visible at the size of the target. */}
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute -inset-px rounded-xl peer-focus-visible:ring-4 peer-focus-visible:ring-brand-500/25"
                    />

                    <span className="flex items-center gap-2.5">
                      <span
                        aria-hidden="true"
                        className={[
                          'flex size-9 shrink-0 items-center justify-center rounded-xl transition-colors duration-150',
                          isActive
                            ? 'bg-brand-100 text-brand-600'
                            : 'bg-surface-muted text-neutral-500 group-hover:text-neutral-700',
                        ].join(' ')}
                      >
                        {CATEGORY_ICONS[value]}
                      </span>
                      <span className="font-display text-sm font-semibold tracking-tight text-neutral-900">
                        {CATEGORY_LABELS[value]}
                      </span>
                    </span>

                    <span className="text-xs leading-relaxed text-neutral-500">
                      {CATEGORY_HELP[value]}
                    </span>
                  </label>
                )
              })}
            </div>
          </fieldset>
        </Panel>

        <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
          <div className="flex min-w-0 flex-1 flex-col gap-4">
        <Panel
          title="Files"
          description={
            pending.length > 0
              ? `${formatCount(pending.length)} queued · ${formatBytes(totalBytes)}`
              : 'PDF, Word, PowerPoint or a scan. One at a time or a whole folder.'
          }
          action={
            pending.length > 0 ? (
              <ActionButton
                variant="secondary"
                size="sm"
                disabled={busy}
                onClick={() => {
                  setPending([])
                  setNotice(null)
                }}
              >
                Clear all
              </ActionButton>
            ) : undefined
          }
        >
          <div className="flex flex-col gap-4">
            <DocumentDropzone
              onFilesAccepted={handleFilesAccepted}
              disabled={busy}
              hint={
                pending.length > 0
                  ? `${formatCount(pending.length)} added · up to 100 MB each`
                  : undefined
              }
            />

            {pending.length > 0 ? (
              <ul className="flex flex-col divide-y divide-hairline overflow-hidden rounded-xl border border-hairline">
                {pending.map((upload) => {
                  const unsupported = fileTypeFromName(upload.file.name) === null

                  return (
                    <li
                      key={upload.id}
                      className={[
                        'flex items-start gap-3 px-3.5 py-3',
                        upload.status === 'rejected' ? 'bg-rose-50/50' : 'bg-surface',
                      ].join(' ')}
                    >
                      <FileGlyph filename={upload.file.name} />

                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-neutral-900">
                          {upload.file.name}
                        </p>
                        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500">
                          <span className="tabular-nums">{formatBytes(upload.file.size)}</span>
                          <span aria-hidden="true">·</span>
                          <PendingStatusMark upload={upload} />
                        </p>

                        {/* The server's own wording, verbatim — a duplicate warning or
                            a refusal reason is more specific than anything this page
                            could paraphrase. */}
                        {upload.message ? (
                          <p
                            className={[
                              'mt-1.5 flex items-start gap-1.5 text-xs leading-relaxed',
                              upload.status === 'rejected'
                                ? 'text-rose-800 dark:text-rose-300'
                                : 'text-amber-800 dark:text-amber-300',
                            ].join(' ')}
                          >
                            <AlertTriangleIcon className="mt-px size-3.5 shrink-0" />
                            <span>{upload.message}</span>
                          </p>
                        ) : null}

                        {/* Belt and braces: the drop zone already refuses these, but a
                            file added before a limit changed would sit here silently. */}
                        {unsupported && upload.status === 'ready' ? (
                          <p className="mt-1.5 text-xs text-rose-800 dark:text-rose-300">
                            This file type is not supported and will be refused.
                          </p>
                        ) : null}
                      </div>

                      <IconAction
                        label={`Remove ${upload.file.name}`}
                        icon={<TrashIcon />}
                        tone="danger"
                        disabled={busy}
                        onClick={() => removeUpload(upload.id)}
                      />
                    </li>
                  )
                })}
              </ul>
            ) : null}

            {notice ? <AlertMessage tone={notice.tone}>{notice.text}</AlertMessage> : null}

            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              {uploadedIds.length > 0 ? (
                <ActionButton
                  variant="primary"
                  leadingIcon={<DatabaseIcon />}
                  disabled={busy}
                  onClick={() => void startIndexing(uploadedIds)}
                >
                  {`Index ${formatCount(uploadedIds.length)} ${
                    uploadedIds.length === 1 ? 'document' : 'documents'
                  }`}
                </ActionButton>
              ) : null}

              <ActionButton
                variant={uploadedIds.length > 0 ? 'secondary' : 'primary'}
                leadingIcon={<UploadIcon />}
                disabled={busy || readyCount === 0}
                onClick={() => void handleUpload()}
              >
                {readyCount === 0
                  ? 'Upload'
                  : `Upload & index ${formatCount(readyCount)} ${
                      readyCount === 1 ? 'file' : 'files'
                    }`}
              </ActionButton>
            </div>
          </div>
        </Panel>
      </div>

      {/*
        Metadata sits beside the flow from `xl` and below it on anything narrower, which
        matches its importance: helpful, never required. The disclosure starts closed so
        the default path is drop-and-send, and opening it is the deliberate act of
        overriding what the tagger would have inferred.
      */}
      <div className="w-full xl:max-w-sm">
        <Panel
          title="Details"
          description="Leave anything blank and VR-Nexus infers it while indexing."
          action={
            <button
              type="button"
              onClick={() => setDetailsOpen((open) => !open)}
              aria-expanded={detailsOpen}
              aria-controls="upload-details"
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
            <div id="upload-details" className="flex flex-col gap-4">
              {/* One file, one title. With a batch the field is not rendered at all —
                  see `handleUpload`, which also clears it from the payload. */}
              {pending.length === 1 ? (
                <MetadataField
                  id="upload-title"
                  label="Title"
                  value={metadata.title}
                  onChange={(value) => setField('title', value)}
                  placeholder="NLC Terminal Operating System"
                  hint="How the document is named in the library, rather than its filename."
                />
              ) : pending.length > 1 ? (
                <AlertMessage tone="neutral" icon={<FileTextIcon />}>
                  Titles are inferred per document while indexing. Everything below
                  applies to all {formatCount(pending.length)} files.
                </AlertMessage>
              ) : null}

              <MetadataField
                id="upload-client"
                label="Client"
                value={metadata.client}
                onChange={(value) => setField('client', value)}
                placeholder="National Logistics Cell (NLC)"
              />
              <MetadataField
                id="upload-doc-type"
                label="Document type"
                value={metadata.doc_type}
                onChange={(value) => setField('doc_type', value)}
                placeholder="Case Study, Certificate, Policy"
              />
              <MetadataField
                id="upload-sector"
                label="Sector"
                value={metadata.sector}
                onChange={(value) => setField('sector', value)}
                placeholder="Logistics"
              />
              <MetadataField
                id="upload-service-line"
                label="Service line"
                value={metadata.service_line}
                onChange={(value) => setField('service_line', value)}
                placeholder="Enterprise Systems"
              />
              <MetadataField
                id="upload-geography"
                label="Geography"
                value={metadata.geography}
                onChange={(value) => setField('geography', value)}
                placeholder="Pakistan"
              />
              <MetadataField
                id="upload-keywords"
                label="Keywords"
                value={metadata.keywords}
                onChange={(value) => setField('keywords', value)}
                placeholder="rfid, gate automation, yard management"
                hint="Comma separated. These sharpen retrieval when a tender uses the same terms."
              />
            </div>
          ) : (
            <p className="text-sm leading-relaxed text-neutral-500">
              Client, sector, service line, geography and keywords are all inferred from
              the document itself. Fill them in only where you want to overrule that.
            </p>
          )}
        </Panel>
      </div>
      </div>
    </div>
  )
}
