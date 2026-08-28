/**
 * The "are you sure" step before something irreversible.
 *
 * Built on the native `<dialog>` element opened with `showModal()`, which is the reason
 * this file is short. That one call gives a focus trap, Escape-to-close, an inert
 * background and the top layer — the four things a div-based modal has to reimplement,
 * and the focus trap in particular is where hand-rolled dialogs go wrong: tab twice and
 * you are behind the overlay, operating a page you cannot see.
 *
 * Deleting a document is not undoable — the row, its chunks and its embeddings all go —
 * so it gets a confirmation. Training does not, so it does not get one. A confirmation
 * on a reversible action teaches people to dismiss confirmations without reading them,
 * which is how the unrecoverable one gets clicked through.
 *
 * The confirm button carries the verb, not "OK". A person reading only the buttons
 * should still know what is about to happen.
 */

import { useEffect, useRef } from 'react'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertTriangleIcon } from '@/components/ui/icons'

type ConfirmDialogProps = {
  open: boolean
  title: string
  description: string
  /** The verb. "Delete document", not "Confirm". */
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current

    if (!dialog) {
      return
    }

    /* `open` is driven by React, but the element's own openness is imperative — setting
       the `open` attribute directly would show the dialog *without* the top layer, the
       backdrop or the focus trap. `showModal()` is what earns all three. */
    if (open && !dialog.open) {
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      /* Escape fires `cancel`; the default would close the element while React still
         believed it was open, so the state goes through the same path as the button. */
      onCancel={(event) => {
        event.preventDefault()
        onCancel()
      }}
      aria-labelledby="confirm-dialog-title"
      aria-describedby="confirm-dialog-description"
      className={[
        'm-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border border-hairline bg-surface p-0',
        'shadow-panel backdrop:bg-ink-950/40',
      ].join(' ')}
    >
      <div className="flex items-start gap-4 p-5 sm:p-6">
        <span
          aria-hidden="true"
          className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-rose-50 text-rose-700"
        >
          <AlertTriangleIcon className="size-5" />
        </span>

        <div className="min-w-0">
          <h2
            id="confirm-dialog-title"
            className="font-display text-base font-semibold tracking-tight text-neutral-900"
          >
            {title}
          </h2>
          <p
            id="confirm-dialog-description"
            className="mt-1.5 text-sm leading-relaxed text-neutral-600"
          >
            {description}
          </p>
        </div>
      </div>

      {/* Cancel first in the DOM so it is the first tab stop, and the destructive
          button is never the one a stray Enter lands on. */}
      <div className="flex flex-col-reverse gap-2 border-t border-hairline px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
        <ActionButton variant="secondary" onClick={onCancel}>
          Cancel
        </ActionButton>
        <ActionButton variant="danger" onClick={onConfirm}>
          {confirmLabel}
        </ActionButton>
      </div>
    </dialog>
  )
}
