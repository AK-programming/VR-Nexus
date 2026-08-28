/**
 * The single text input used across the auth screens.
 *
 * Everything a field needs travels together — label, icon, error, hint and the
 * password reveal — so a form is a list of fields rather than a list of divs, and
 * so the accessibility wiring (`aria-invalid`, `aria-describedby`, the label's
 * `htmlFor`) cannot be forgotten on one field and remembered on another.
 *
 * The icon sits on a tinted plate that fills with brand red while the field has
 * focus. It is the only moving part: with eight fields on the registration screen,
 * anything more would turn typing into a light show.
 */

import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangleIcon, EyeIcon, EyeOffIcon } from '@/components/ui/icons'

type TextFieldProps = {
  label: string
  name: string
  value: string
  onChange: (value: string) => void
  icon: ReactNode

  /** `password` swaps in the reveal toggle; the rest only pick the soft keyboard. */
  type?: 'text' | 'email' | 'password' | 'tel'
  placeholder?: string
  autoComplete?: string
  maxLength?: number
  disabled?: boolean

  /** The message under the field. Its presence is what puts the field in an error state. */
  error?: string

  /** Standing guidance, shown only while there is no error to show instead. */
  hint?: string

  /** Marks the field as not required, in the label rather than by its absence. */
  optional?: boolean

  /** Extra content below the input — the password strength meter uses this. */
  footer?: ReactNode

  /** Right-aligned content in the label row, such as "Forgot password?". */
  labelAction?: ReactNode
}

export function TextField({
  label,
  name,
  value,
  onChange,
  icon,
  type = 'text',
  placeholder,
  autoComplete,
  maxLength,
  disabled = false,
  error,
  hint,
  optional = false,
  footer,
  labelAction,
}: TextFieldProps) {
  const inputId = useId()
  const messageId = `${inputId}-message`
  const [isRevealed, setIsRevealed] = useState(false)

  const isPassword = type === 'password'
  const resolvedType = isPassword && isRevealed ? 'text' : type
  const message = error ?? hint

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={inputId} className="text-sm font-medium text-neutral-700">
          {label}
          {/* neutral-500, not 400. "Optional" changes what the form expects of the
              person reading it, so it is information rather than decoration and has
              to clear 4.5:1 — which neutral-400 on white does not. */}
          {optional ? <span className="ml-1.5 text-xs text-neutral-500">Optional</span> : null}
        </label>
        {labelAction}
      </div>

      {/*
        h-11 — 44px — is the height, stated outright rather than left to add up
        from padding. Padding-derived heights drift: this field used to measure
        54px because a 32px icon plate and py-2.5 happened to sum to that, which
        is not a number on any scale and did not match anything else on the form.
        44px is on the scale, is the tap-target minimum, and sits one step under
        the 48px submit button — so the plate inside can change size without the
        field resizing under it.

        Only the horizontal padding is set, and items-center distributes what is
        left over — so nothing here can knock the height off 44px.
      */}
      <div
        className={[
          'mt-1.5 flex h-11 items-center gap-2.5 rounded-xl border px-3 transition-colors',
          'focus-within:bg-surface focus-within:ring-4',
          error
            ? 'border-brand-300 bg-brand-50/60 focus-within:border-brand-500 focus-within:ring-brand-500/15'
            : 'border-hairline bg-field focus-within:border-brand-400 focus-within:ring-brand-500/15',
          disabled ? 'opacity-60' : '',
        ].join(' ')}
      >
        <span
          className={[
            /* `[&>svg]` sizes whichever icon is handed in, so no call site has to
               remember the icon size and none of them can disagree. size-7 in a
               44px field leaves 7px of breathing room top and bottom — the plate
               reads as sitting inside the field rather than lining it. */
            'flex size-7 shrink-0 items-center justify-center rounded-lg transition-colors [&>svg]:size-4',
            error ? 'bg-brand-100 text-brand-600' : 'bg-brand-50 text-brand-500',
          ].join(' ')}
        >
          {icon}
        </span>

        <input
          id={inputId}
          name={name}
          type={resolvedType}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete}
          maxLength={maxLength}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={message ? messageId : undefined}
          className="h-full min-w-0 flex-1 bg-transparent text-sm text-neutral-900 placeholder:text-neutral-400 focus:outline-none disabled:cursor-not-allowed"
        />

        {isPassword ? (
          <button
            type="button"
            onClick={() => setIsRevealed((revealed) => !revealed)}
            /* The label states the action, not the state, so a screen reader
               hears what pressing it will do rather than what it did. */
            aria-label={isRevealed ? 'Hide password' : 'Show password'}
            aria-pressed={isRevealed}
            className="-mr-1 flex size-7 shrink-0 items-center justify-center rounded-lg text-neutral-400 transition-colors hover:bg-white hover:text-neutral-700"
          >
            {isRevealed ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
          </button>
        ) : null}
      </div>

      {footer}

      {message ? (
        <p
          id={messageId}
          className={[
            'mt-1.5 flex items-start gap-1.5 text-xs leading-snug',
            error ? 'text-brand-600' : 'text-neutral-500',
          ].join(' ')}
        >
          {error ? <AlertTriangleIcon className="mt-px size-3.5 shrink-0" /> : null}
          <span>{message}</span>
        </p>
      ) : null}
    </div>
  )
}
