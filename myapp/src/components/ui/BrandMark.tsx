/**
 * The VR-Nexus mark: a V inside a hexagon.
 *
 * Flat `currentColor` rather than a gradient, deliberately. A gradient needs
 * `<defs>` and therefore an id, and this mark renders twice on a phone-width page
 * — once in the navigation rail, once in the header — which is exactly the setup
 * where two elements quietly share one gradient id and only one of them is right.
 * Colour comes from the caller, like every other icon in the set.
 *
 * The hexagon is the shape already used for the seam badge on the sign-in screen,
 * so the two screens are carrying the same geometry rather than two ideas of it.
 */

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <path d="M16 2.5 27.5 9v14L16 29.5 4.5 23V9Z" fill="currentColor" />
      <path
        d="m11 12.5 5 8 5-8"
        fill="none"
        stroke="#ffffff"
        strokeWidth="2.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/**
 * The name, set once so the tracking and the two-line lockup cannot drift between
 * the rail and the header.
 *
 * `tone` exists because the mark sits on ink in the rail and on white in the
 * mobile header, and inverting a wordmark is not something to leave to whichever
 * text colour happens to be inherited.
 */
export function BrandWordmark({ tone = 'light' }: { tone?: 'light' | 'dark' }) {
  return (
    <span className="flex flex-col leading-none">
      <span
        className={[
          'font-display text-sm font-semibold tracking-[0.16em]',
          tone === 'light' ? 'text-white' : 'text-neutral-900',
        ].join(' ')}
      >
        VR-NEXUS
      </span>
      <span
        className={[
          'mt-1 text-[0.625rem] tracking-[0.18em] uppercase',
          tone === 'light' ? 'text-neutral-400' : 'text-neutral-500',
        ].join(' ')}
      >
        Tender Intelligence
      </span>
    </span>
  )
}
