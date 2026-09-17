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
    <span className="flex min-w-0 flex-col leading-none">
      <span
        className={[
          'truncate font-display text-sm font-semibold tracking-[0.14em]',
          tone === 'light' ? 'text-white' : 'text-neutral-900',
        ].join(' ')}
      >
        VR-NEXUS
      </span>
      {/* Smaller and less tracked than the wordmark above it (client follow-up
          request) — at the old size/tracking this wrapped onto two lines
          ("TENDER" / "INTELLIGENCE") in the sidebar's narrow header, throwing
          it out of alignment with the logo mark beside it. `whitespace-nowrap`
          plus the smaller size keeps it on one line and baseline-aligned
          under "VR-NEXUS" at the sidebar's normal width. */}
      <span
        className={[
          'mt-0.5 whitespace-nowrap text-[0.5rem] tracking-[0.1em] uppercase',
          tone === 'light' ? 'text-neutral-400' : 'text-neutral-500',
        ].join(' ')}
      >
        Tender Intelligence
      </span>
    </span>
  )
}
