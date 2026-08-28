/**
 * The drop target for a tender, on react-dropzone.
 *
 * A sibling of the documents `DocumentDropzone`, and a separate component rather
 * than a shared one for a concrete reason: that dropzone hard-codes the library's
 * accept map and 100 MB limit from `models/documents`, and a tender validates
 * against a *narrower* rule — PDF only (`TENDER_DROPZONE_ACCEPT`), because
 * `validate_tender_upload` on the server rejects anything else and PyMuPDF reads
 * pages, not Word files. Wiring the library's constants into a tender screen would
 * accept a `.docx` the client should refuse locally, spending a 100 MB upload to
 * earn a 400. So the two share a shape, not a vocabulary — exactly as the two
 * status pills and the two progress hooks do.
 *
 * Single file, always. A tender *is* one formal PDF, so this takes
 * `onFileAccepted(file)` rather than the library's `onFilesAccepted(files[])` and
 * pins `multiple: false` — the metadata form on the upload screen describes one
 * document, and letting two through would leave the second nowhere to go.
 *
 * Validation mirrors the server rather than inventing rules: `TENDER_DROPZONE_ACCEPT`
 * lists the same extension `validate_tender_upload` accepts and
 * `TENDER_MAX_UPLOAD_BYTES` is the same ceiling. The point is to refuse locally
 * exactly what the server would refuse remotely, no stricter and no looser.
 *
 * Accessibility: react-dropzone puts `tabIndex=0` and Space/Enter handling on the
 * root and hides the real input, so the zone is one tab stop that opens the file
 * dialog. There is deliberately no nested "Browse" button — a button inside an
 * already-activatable region gives the same action two tab stops and two names.
 */

import { useDropzone } from 'react-dropzone'
import type { FileRejection } from 'react-dropzone'
import {
  TENDER_ACCEPTED_EXTENSIONS,
  TENDER_DROPZONE_ACCEPT,
  TENDER_MAX_UPLOAD_BYTES,
  TENDER_MAX_UPLOAD_MB,
} from '@/models/tenders'
import { formatBytes } from '@/lib/formatting'
import { AlertTriangleIcon, UploadIcon } from '@/components/ui/icons'

type TenderDropzoneProps = {
  /** Called with the single file that passed the type and size checks. */
  onFileAccepted: (file: File) => void
  /** Closes the zone while an upload is in flight, or once a file is chosen. */
  disabled?: boolean
  /** Replaces the second line — for naming the chosen file, say. */
  hint?: string
}

/**
 * Turns a rejection code into a sentence a person can act on.
 *
 * react-dropzone's own messages are developer-facing ("File is larger than
 * 104857600 bytes"). These name the limit in the units the hint line uses, so the
 * rule and the violation are stated the same way.
 */
function rejectionMessage(rejection: FileRejection): string {
  const code = rejection.errors[0]?.code

  if (code === 'file-too-large') {
    return `${formatBytes(rejection.file.size)} — the limit is ${TENDER_MAX_UPLOAD_MB} MB.`
  }

  if (code === 'file-invalid-type') {
    return `Not a supported file. A tender must be a ${TENDER_ACCEPTED_EXTENSIONS}.`
  }

  if (code === 'too-many-files') {
    return 'One tender at a time — drop a single PDF.'
  }

  /* An empty file passes both checks above and fails on the server, which rejects
     size 0 outright. Catching it here saves the round trip. */
  if (rejection.file.size === 0) {
    return 'That file is empty.'
  }

  return rejection.errors[0]?.message ?? 'That file could not be added.'
}

export function TenderDropzone({ onFileAccepted, disabled = false, hint }: TenderDropzoneProps) {
  const { getRootProps, getInputProps, isDragActive, isDragReject, fileRejections } = useDropzone({
    accept: TENDER_DROPZONE_ACCEPT,
    maxSize: TENDER_MAX_UPLOAD_BYTES,
    /* The server rejects a zero-byte upload, so refuse it before sending. */
    minSize: 1,
    multiple: false,
    disabled,
    onDrop: (accepted) => {
      const file = accepted[0]
      if (file) {
        onFileAccepted(file)
      }
    },
  })

  return (
    <div>
      <div
        {...getRootProps({
          className: [
            'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-10 text-center',
            'transition-colors duration-150',
            disabled
              ? 'cursor-not-allowed border-hairline bg-surface-muted opacity-60'
              : isDragReject
                ? 'border-rose-300 bg-rose-50'
                : isDragActive
                  ? 'border-brand-400 bg-brand-50'
                  : 'border-neutral-300 bg-surface-muted hover:border-brand-400 hover:bg-brand-50/40',
          ].join(' '),
        })}
      >
        <input {...getInputProps()} />

        <span
          aria-hidden="true"
          className={[
            'flex size-12 items-center justify-center rounded-xl border transition-colors duration-150',
            isDragActive && !isDragReject
              ? 'border-brand-200 bg-brand-100 text-brand-600'
              : 'border-hairline bg-surface text-neutral-500',
          ].join(' ')}
        >
          <UploadIcon className="size-5" />
        </span>

        <div>
          <p className="text-sm font-semibold text-neutral-900">
            {isDragReject
              ? 'That file type is not accepted'
              : isDragActive
                ? 'Drop to add'
                : 'Drag the tender here, or click to choose'}
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            {hint ?? `${TENDER_ACCEPTED_EXTENSIONS} · up to ${TENDER_MAX_UPLOAD_MB} MB`}
          </p>
        </div>
      </div>

      {/*
        Rejections live under the zone rather than inside it, so the zone keeps its
        size and a second attempt is not chasing a moving target. `aria-live` because
        a keyboard user who picked a file through the dialog gets no other signal that
        it was refused.
      */}
      {fileRejections.length > 0 ? (
        <ul aria-live="polite" className="mt-3 flex flex-col gap-2">
          {fileRejections.map((rejection) => (
            <li
              key={`${rejection.file.name}-${rejection.file.size}`}
              className="flex items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5"
            >
              <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-rose-700" />
              <p className="min-w-0 text-xs leading-relaxed text-rose-900">
                <span className="font-semibold break-all">{rejection.file.name}</span>{' '}
                {rejectionMessage(rejection)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
