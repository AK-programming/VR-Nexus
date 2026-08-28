/**
 * The drop target, on react-dropzone.
 *
 * Why the dependency at all, when `onDragOver` plus an `<input type="file">` is twenty
 * lines: the twenty lines are not the hard part. Drag events fire on every child
 * element, so a naive `onDragLeave` clears the active state the moment the pointer
 * crosses the icon inside the zone; the counter that fixes that is the bug everyone
 * writes once. Add `dataTransfer.items` normalisation across browsers, keyboard
 * activation, and per-file accept/size filtering, and the package is smaller than the
 * correct hand-rolled version. It also gives the *reasons* a file was refused, which
 * is what turns "upload failed" into "that file is 118 MB".
 *
 * Validation here mirrors the server rather than inventing rules: `DROPZONE_ACCEPT`
 * lists the same extensions `storage.validate_upload` accepts, and `MAX_UPLOAD_BYTES`
 * is the same 100 MB. The point is not to be strict, it is to refuse locally exactly
 * what the server would refuse remotely — a stricter client rejects files that would
 * have worked, and a looser one spends a 100 MB upload to earn a 400.
 *
 * Accessibility: react-dropzone puts `tabIndex=0` and Space/Enter handling on the root
 * and hides the real input, so the zone is one tab stop that opens the file dialog.
 * There is deliberately no "Browse" button inside it — a button nested in an already
 * activatable region gives the same action two tab stops and two names.
 */

import { useDropzone } from 'react-dropzone'
import type { FileRejection } from 'react-dropzone'
import {
  ACCEPTED_EXTENSIONS,
  DROPZONE_ACCEPT,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_MB,
} from '@/models/documents'
import { formatBytes } from '@/lib/formatting'
import { AlertTriangleIcon, UploadIcon } from '@/components/ui/icons'

type DocumentDropzoneProps = {
  /** Called with the files that passed type and size checks. */
  onFilesAccepted: (files: File[]) => void
  /** One file at a time, for a flow that needs metadata per document. */
  multiple?: boolean
  /** Closes the zone while an upload is in flight, or once a limit is reached. */
  disabled?: boolean
  /** Replaces the second line — for saying "3 of 10 added", say. */
  hint?: string
}

/**
 * Turns a rejection code into a sentence a person can act on.
 *
 * react-dropzone's own messages are developer-facing ("File is larger than 104857600
 * bytes"). These name the limit in the units the hint line uses, so the rule and the
 * violation are stated the same way.
 */
function rejectionMessage(rejection: FileRejection): string {
  const code = rejection.errors[0]?.code

  if (code === 'file-too-large') {
    return `${formatBytes(rejection.file.size)} — the limit is ${MAX_UPLOAD_MB} MB.`
  }

  if (code === 'file-invalid-type') {
    return `Not a supported file. Add ${ACCEPTED_EXTENSIONS}.`
  }

  if (code === 'too-many-files') {
    return 'Only one file at a time here.'
  }

  /* An empty file passes both checks above and fails on the server, which rejects
     size 0 outright. Catching it here saves the round trip. */
  if (rejection.file.size === 0) {
    return 'That file is empty.'
  }

  return rejection.errors[0]?.message ?? 'That file could not be added.'
}

export function DocumentDropzone({
  onFilesAccepted,
  multiple = true,
  disabled = false,
  hint,
}: DocumentDropzoneProps) {
  const { getRootProps, getInputProps, isDragActive, isDragReject, fileRejections } = useDropzone({
    accept: DROPZONE_ACCEPT,
    maxSize: MAX_UPLOAD_BYTES,
    /* The server rejects a zero-byte upload, so refuse it before sending. */
    minSize: 1,
    multiple,
    disabled,
    onDrop: (accepted) => {
      if (accepted.length > 0) {
        onFilesAccepted(accepted)
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
                : multiple
                  ? 'Drag documents here, or click to choose'
                  : 'Drag a document here, or click to choose'}
          </p>
          <p className="mt-1 text-xs text-neutral-500">
            {hint ?? `${ACCEPTED_EXTENSIONS} · up to ${MAX_UPLOAD_MB} MB each`}
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
