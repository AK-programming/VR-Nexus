/**
 * The two buttons these screens need, and no more.
 *
 * `primary` is the red gradient with the halo under it — the one loud element on
 * the form side, so there is never a question about where the form ends.
 * `secondary` is a quiet bordered button for the alternative route.
 *
 * The surfaces themselves come from `ui/surfaces`, shared with the dashboard
 * header's action button. Only the sizing is decided here.
 */

import type { ReactNode } from 'react'
import { SpinnerIcon } from '@/components/ui/icons'
import { BRAND_SURFACE, QUIET_SURFACE } from '@/components/ui/surfaces'

type ButtonProps = {
  children: ReactNode
  variant?: 'primary' | 'secondary'
  type?: 'button' | 'submit'
  onClick?: () => void
  disabled?: boolean

  /** Swaps the label for a spinner and blocks input, without changing the button's width. */
  loading?: boolean

  /** What the spinner state says. Silence here would leave a submitting form unlabelled. */
  loadingLabel?: string

  leadingIcon?: ReactNode
  trailingIcon?: ReactNode
}

export function Button({
  children,
  variant = 'primary',
  type = 'button',
  onClick,
  disabled = false,
  loading = false,
  loadingLabel = 'Working…',
  leadingIcon,
  trailingIcon,
}: ButtonProps) {
  return (
    <button
      type={type}
      onClick={onClick}
      /* Disabled *and* loading, so a double-tap on a slow connection cannot submit
         the form twice. aria-busy tells assistive tech the wait is expected. */
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={[
        /* h-12 — 48px — stated, not accumulated from py-3 plus whatever the font
           happens to make of a line box. It is one step above the 44px fields, so
           the submit control is visibly the heaviest thing in the form without
           needing a second colour to say so, and both numbers are on the scale.

           No py: a fixed height plus items-center is what keeps the label centred,
           and vertical padding on top of that would only fight it. */
        'flex h-12 w-full items-center justify-center gap-2.5 rounded-xl px-5',
        'font-display text-base font-semibold tracking-tight',
        'transition-all duration-200 [&>svg]:size-5',
        'disabled:pointer-events-none disabled:opacity-55',
        variant === 'primary' ? BRAND_SURFACE : QUIET_SURFACE,
      ].join(' ')}
    >
      {loading ? (
        <>
          <SpinnerIcon className="animate-spin" />
          <span>{loadingLabel}</span>
        </>
      ) : (
        <>
          {leadingIcon}
          <span>{children}</span>
          {trailingIcon}
        </>
      )}
    </button>
  )
}
