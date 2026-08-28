/**
 * The inline button the content pages use.
 *
 * `Button` in this folder is a form submit: 48px tall and `w-full`, because that is
 * what the bottom of a sign-in form wants. A table row action, a toolbar and a panel
 * header all want the opposite — shrink to the label, sit on a row with three others.
 * Rather than add a `size` and a `fullWidth` prop to `Button` and have every caller
 * negotiate, this is the inline one. Both draw their colour from `ui/surfaces`, so the
 * red is the same red and always will be.
 *
 * `to` turns it into a `Link` and keeps the paint. A navigation dressed as a button is
 * still a navigation — rendering it as a real anchor is what gives it middle-click,
 * "copy link", and the status bar preview a `<button onClick={navigate}>` throws away.
 *
 * `danger` is rose rather than brand red. Red is the logo, the primary action and the
 * active nav marker in this product, so a red Delete would read as the most encouraged
 * thing on screen. Rose carries the warning without joining the brand.
 */

import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { BRAND_SURFACE, QUIET_SURFACE } from '@/components/ui/surfaces'

type ActionButtonVariant = 'primary' | 'secondary' | 'danger'
type ActionButtonSize = 'sm' | 'md'

const VARIANT_CLASSES: Record<ActionButtonVariant, string> = {
  primary: BRAND_SURFACE,
  secondary: QUIET_SURFACE,
  danger: [
    'border border-rose-200 bg-rose-50 text-rose-700',
    'hover:border-rose-300 hover:bg-rose-100 hover:text-rose-900',
    'active:translate-y-px',
  ].join(' '),
}

/** Heights on Tailwind's scale, stated rather than accumulated out of padding. */
const SIZE_CLASSES: Record<ActionButtonSize, string> = {
  sm: 'h-8 gap-1.5 rounded-lg px-2.5 text-xs [&>svg]:size-3.5',
  md: 'h-10 gap-2 rounded-xl px-3.5 text-sm [&>svg]:size-4',
}

type SharedProps = {
  children: ReactNode
  variant?: ActionButtonVariant
  size?: ActionButtonSize
  leadingIcon?: ReactNode
  /**
   * For a button whose direction is the point — Next, Open, Continue. A trailing
   * chevron on a "Next" reads as forward motion where a leading one reads as a
   * decoration pointing back at nothing.
   */
  trailingIcon?: ReactNode
  /** Collapses the label below `sm` so a four-button toolbar still fits at 375px. */
  hideLabelOnMobile?: boolean
  className?: string
}

type ActionButtonProps = SharedProps & {
  onClick?: () => void
  type?: 'button' | 'submit'
  disabled?: boolean
  /** Renders a `Link` instead of a `button`. Ignores `onClick`, `type` and `disabled`. */
  to?: string
}

export function ActionButton({
  children,
  variant = 'secondary',
  size = 'md',
  leadingIcon,
  trailingIcon,
  hideLabelOnMobile = false,
  className,
  onClick,
  type = 'button',
  disabled = false,
  to,
}: ActionButtonProps) {
  const classes = [
    'inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap',
    'transition-all duration-150',
    SIZE_CLASSES[size],
    VARIANT_CLASSES[variant],
    disabled ? 'pointer-events-none opacity-55' : '',
    className ?? '',
  ].join(' ')

  /* The label is hidden with `sr-only`, not removed: the button keeps its accessible
     name at every width, so a narrow viewport does not turn four buttons into four
     unnamed glyphs. Only the label collapses — the icons are what is left to look at. */
  const label = hideLabelOnMobile ? (
    <span className="sr-only sm:not-sr-only">{children}</span>
  ) : (
    <span>{children}</span>
  )

  if (to) {
    return (
      <Link to={to} className={classes}>
        {leadingIcon}
        {label}
        {trailingIcon}
      </Link>
    )
  }

  return (
    <button type={type} onClick={onClick} disabled={disabled} className={classes}>
      {leadingIcon}
      {label}
      {trailingIcon}
    </button>
  )
}

/**
 * The icon-only action for a table row.
 *
 * Separate from `ActionButton` because it needs the one thing that component must
 * never allow: no visible label. That is only defensible in a row that repeats the
 * same two actions twenty times, where the labels become a wall of text and the
 * column they force costs more than they explain — so `label` is required here and
 * becomes both the accessible name and the native tooltip.
 */
export function IconAction({
  label,
  icon,
  onClick,
  disabled = false,
  tone = 'neutral',
}: {
  label: string
  icon: ReactNode
  onClick?: () => void
  disabled?: boolean
  tone?: 'neutral' | 'danger'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className={[
        'inline-flex size-8 items-center justify-center rounded-lg border border-transparent',
        'transition-colors duration-150',
        'disabled:pointer-events-none disabled:opacity-40',
        tone === 'danger'
          ? 'text-neutral-500 hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700'
          : 'text-neutral-500 hover:border-hairline hover:bg-surface-muted hover:text-neutral-900',
        '[&>svg]:size-4',
      ].join(' ')}
    >
      {icon}
    </button>
  )
}
