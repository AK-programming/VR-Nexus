/**
 * One inline message block, in five tones.
 *
 * `role` follows the tone rather than being a prop: a failure needs announcing the
 * moment it appears, so it is `alert`; a confirmation can wait for a natural pause,
 * so it is `status`. Getting that backwards either interrupts a screen-reader user
 * mid-sentence or lets them submit a form twice without knowing the first attempt
 * failed.
 */

import type { ReactNode } from 'react'

export type AlertTone = 'error' | 'warning' | 'neutral' | 'success' | 'info'

const TONE_SURFACE: Record<AlertTone, string> = {
  error: 'border-brand-200 bg-brand-50 text-brand-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  neutral: 'border-hairline bg-surface-muted text-neutral-700',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  info: 'border-sky-200 bg-sky-50 text-sky-800',
}

type AlertMessageProps = {
  tone: AlertTone
  children: ReactNode
  icon?: ReactNode

  /** A short heading, for the cases where the message alone does not say what happened. */
  title?: string
}

export function AlertMessage({ tone, children, icon, title }: AlertMessageProps) {
  return (
    <div
      role={tone === 'error' || tone === 'warning' ? 'alert' : 'status'}
      className={[
        'flex items-start gap-3 rounded-xl border px-3.5 py-3 [&>svg]:mt-px [&>svg]:size-4 [&>svg]:shrink-0',
        TONE_SURFACE[tone],
      ].join(' ')}
    >
      {icon}
      <div className="text-sm leading-snug">
        {title ? <p className="font-display font-semibold">{title}</p> : null}
        <p className={title ? 'mt-0.5 opacity-90' : undefined}>{children}</p>
      </div>
    </div>
  )
}
