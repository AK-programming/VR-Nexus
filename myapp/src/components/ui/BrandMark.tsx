/**
 * The VR-Nexus mark — the supplied logo, served from /vr-nexus-logo.png (Vite
 * `public/`). It is a wide emblem (≈1.6:1), so callers size it by HEIGHT and let
 * the width follow (`h-8 w-auto`); passing a square size would squash it. Colour
 * comes from the raster, so unlike the old inline SVG there is no `currentColor`
 * to set — the `object-contain` keeps it crisp at any height.
 */

export function BrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/vr-nexus-logo.png"
      alt=""
      aria-hidden="true"
      className={['object-contain', className ?? ''].join(' ')}
    />
  )
}

/**
 * The name, set once so the tracking and the two-line lockup cannot drift between
 * the rail and the header. `tone` inverts it for the ink rail vs the light header.
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
