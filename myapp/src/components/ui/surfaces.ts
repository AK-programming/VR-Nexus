/**
 * The product's two button surfaces, in one place.
 *
 * Only the paint lives here — colour, border, shadow, press behaviour. Size,
 * radius and layout stay with each caller, because a 48px form submit and a 40px
 * header action are the same brand red at deliberately different weights and
 * should not be forced to share a height to share a colour.
 *
 * The gradients are arbitrary values reading straight from the theme tokens, so
 * the button's red and the brand panel's red are guaranteed to be the same red:
 * change --color-brand-500 in index.css and every one of these follows.
 */

export const BRAND_SURFACE = [
  'text-white shadow-glow',
  'bg-[linear-gradient(96deg,var(--color-brand-500)_0%,var(--color-brand-700)_100%)]',
  'hover:bg-[linear-gradient(96deg,var(--color-brand-400)_0%,var(--color-brand-600)_100%)]',
  'active:translate-y-px',
].join(' ')

export const QUIET_SURFACE = [
  'border border-hairline bg-surface text-neutral-700',
  'hover:border-neutral-300 hover:bg-surface-muted hover:text-neutral-900',
  'active:translate-y-px',
].join(' ')
