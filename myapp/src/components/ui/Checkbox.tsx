/**
 * A checkbox with a real <input> underneath.
 *
 * The native control is visually hidden but still focusable and still toggles with
 * Space, so keyboard and screen-reader behaviour come for free; the visible square
 * is the <label>, which is why clicking it works without a click handler.
 *
 * The description sits *outside* the label on purpose. The terms checkbox needs
 * links in its text, and a link inside a <label> is a trap: the click both follows
 * the link and toggles the box. Keeping them separate means `aria-label` names the
 * control, `aria-describedby` attaches the sentence, and the links behave like
 * links.
 */

import { useId } from 'react'
import type { ReactNode } from 'react'
import { CheckIcon } from '@/components/ui/icons'

type CheckboxProps = {
  /** The control's accessible name. Plain text — this is what a screen reader announces. */
  label: string

  checked: boolean
  onChange: (checked: boolean) => void

  /** The visible sentence. May contain links. Falls back to `label` when omitted. */
  children?: ReactNode

  /** Puts the box in an error state and shows the message below. */
  error?: string

  disabled?: boolean
}

export function Checkbox({
  label,
  checked,
  onChange,
  children,
  error,
  disabled = false,
}: CheckboxProps) {
  const inputId = useId()
  const descriptionId = `${inputId}-description`
  const errorId = `${inputId}-error`

  return (
    <div>
      {/* relative: the sr-only input below needs a containing block of its
          own. Without one it positions against the document root instead of
          this row, which can escape a distant ancestor's overflow clipping and
          quietly grow the whole page's scroll height. */}
      <div className="relative flex items-start gap-3">
        <input
          id={inputId}
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          aria-label={label}
          aria-describedby={error ? `${descriptionId} ${errorId}` : descriptionId}
          aria-invalid={error ? true : undefined}
        />

        <label
          htmlFor={inputId}
          className={[
            /* size-5 rather than an arbitrary 18px: on the same scale as the rest
               of the controls. No top nudge is needed now — a 20px box against the
               19.25px line box of text-sm/leading-snug already reads as aligned,
               and the 1px offset the smaller box wanted would now push it low. */
            'flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-md border',
            'text-transparent transition-all duration-150',
            'peer-checked:text-white peer-checked:border-brand-500 peer-checked:bg-brand-500',
            'peer-focus-visible:ring-4 peer-focus-visible:ring-brand-500/25',
            'peer-disabled:cursor-not-allowed peer-disabled:opacity-55',
            error ? 'border-brand-400 bg-brand-50' : 'border-neutral-300 bg-surface',
            /* Hover only sharpens an empty box. Written as a plain
               `hover:border-brand-400` it ties with `peer-checked:border-brand-500`
               on specificity, so a checked-and-hovered box would be decided by the
               order Tailwind happens to emit the two rules in. `checked` is already
               a prop here, so there is nothing to gamble on. */
            !checked && !error ? 'hover:border-brand-400' : '',
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <CheckIcon className="size-3.5" />
        </label>

        <p id={descriptionId} className="text-sm leading-snug text-neutral-600">
          {children ?? label}
        </p>
      </div>

      {/* pl-8 lines the message up with the sentence above it: a 20px box plus a
          12px gap is exactly 32px. */}
      {error ? (
        <p id={errorId} className="mt-1.5 pl-8 text-xs text-brand-600">
          {error}
        </p>
      ) : null}
    </div>
  )
}
