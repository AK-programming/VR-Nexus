/**
 * The shell both auth screens share: the brand panel, the form panel, and the badge
 * on the seam between them. Two panels, edge to edge, nothing else.
 *
 * Two rules shape it.
 *
 * The page is exactly the viewport and never scrolls as a whole. The brand panel and
 * the badge hold still; only the form column scrolls, and only when it genuinely
 * cannot fit. Sign-in never needs it. Registration needs it on a short laptop, and
 * there the alternative was compressing eight fields until they looked cramped on
 * every screen to spare one screen a scrollbar.
 *
 * The seam between the two panels turns. On a phone it is horizontal: the brand is
 * a strip along the top and the light sheet slides up over its bottom edge. From
 * laptop up the same relationship stands on end and the seam runs vertically down
 * the left. The badge is centred on the seam either way, which is the whole reason
 * it is drawn with pseudo-elements — one element, one transform, two anchor points.
 *
 * The copyright is the last line of the form column. It had its own strip under the
 * panels for a while, and a band of dark across the foot of the screen carrying one
 * small grey sentence read as leftover space rather than as a baseline — it cut the
 * white sheet short for no gain. Inside the column it is simply the quietest line on
 * the page, a step smaller than the link above it, and the panels get the full
 * height of the window back.
 */

import type { ReactNode } from 'react'

/**
 * The brand panel is one flattened composition: the wordmark, the strapline, the ×
 * that reads as "VR-Nexus by DPL", the partner mark, the cityscape and the closing
 * line are all in the file. Nothing is redrawn on top of it — live text over baked
 * text only ever fights it.
 *
 * The spaces in the filename are legal in an import specifier. If it is ever tidied
 * up to brand-panel.png, this is the only line that has to change.
 */
import brandPanel from '@/assets/Login Page side.png'

type AuthLayoutProps = {
  /** The glyph inside the hexagon. A padlock for signing in, a person for signing up. */
  badge: ReactNode

  /**
   * How wide the form column runs. `wide` is for the two-column registration
   * form; `narrow` keeps the sign-in fields at a comfortable reading measure
   * instead of stretching them across the panel.
   */
  width?: 'narrow' | 'wide'

  children: ReactNode
}

export function AuthLayout({ badge, width = 'narrow', children }: AuthLayoutProps) {
  /** The reading measure for the form column, copyright included. */
  const columnWidth = width === 'wide' ? 'max-w-[34rem]' : 'max-w-[25rem]'

  return (
    /* h-dvh, not min-h-dvh: the shell is pinned to the viewport, and overflow-hidden
       here is what guarantees the page itself has nothing to scroll. Because there
       is no page scroll, mobile browser chrome never retracts, so dvh stays put
       instead of resizing under the layout.

       Back to one flex container holding the two panels directly. The intermediate
       row existed only to keep the footer underneath them; with the footer gone the
       phone/laptop switch belongs here again, and the panels reach the bottom edge
       of the window at every width.

       bg-ink-950 stays even though nothing shows through it now — it is what the
       overscroll rubber-band and the area behind a rounded corner land on. */
    <div className="flex h-dvh flex-col overflow-hidden bg-ink-950 lg:flex-row">
      {/* h-full is safe again from lg: this panel is a child of the h-dvh element
          itself, so the percentage resolves against a height that is already
          definite rather than one flexbox has only just computed. */}
      <aside className="relative h-[clamp(7rem,22dvh,11rem)] shrink-0 overflow-hidden lg:h-full lg:w-[45%] lg:min-w-[24rem]">
        <img
          src={brandPanel}
          alt="VR-Nexus, in partnership with DPL"
          /* The artwork is portrait, so on a phone the strip shows a window onto it
             rather than the whole thing. 26% down the image is where the VR mark and
             the wordmark sit, so that is what stays in frame — object-top would slice
             the logo in half, and object-center would land on the cityscape. From lg
             the panel is tall enough for the full composition. */
          className="absolute inset-0 size-full object-cover object-[50%_26%] lg:object-center"
        />

        {/* A touch of extra dark along the seam edge, so the light panel lands on
            depth instead of on whichever part of the artwork happens to be bright.
            Vertical on mobile because the seam is horizontal, and the other way
            round from lg — the gradient turns with the layout.

            Written as an arbitrary *property* rather than bg-[linear-gradient(…)],
            which relies on Tailwind inferring that a gradient is an image. Naming
            background-image outright cannot be inferred wrong. */}
        <div
          aria-hidden="true"
          className="absolute inset-0 [background-image:linear-gradient(180deg,transparent_55%,rgba(10,1,2,0.55)_100%)] lg:[background-image:linear-gradient(90deg,transparent_60%,rgba(10,1,2,0.5)_100%)]"
        />
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Form panel                                                         */}
      {/* ------------------------------------------------------------------ */}
      <main
        className={[
          /* min-h-0 is load-bearing, not tidiness: a flex child defaults to
             min-height:auto, which refuses to shrink below its content and would
             push the panel past the viewport instead of letting the column inside
             it scroll. */
          'relative z-10 flex min-h-0 flex-1 flex-col bg-surface shadow-panel',
          /* Corners are named individually rather than using rounded-t / rounded-l,
             because those two overlap on the top-left and the winner would come
             down to stylesheet order rather than intent.

             The bottom edge stays square because it is the bottom edge of the window
             now — there is nothing below it to show through a curve, so rounding it
             would only shave two slivers of dark off the corners of the sheet.
             rounded-bl-panel is the exception: from lg that curve falls over the
             brand panel, where there is artwork behind it to see. */
          '-mt-7 rounded-tl-[1.75rem] rounded-tr-[1.75rem]',
          'lg:mt-0 lg:-ml-10 lg:rounded-tr-none lg:rounded-tl-panel lg:rounded-bl-panel',
        ].join(' ')}
      >
        {/*
          Decoration, clipped to the panel's own rounding. It is kept in its own
          layer so the badge below can overhang the panel edge without being
          clipped along with it.

          The rings echo the concentric HUD circles in the artwork on the other
          side of the seam, drawn as hairlines rather than blurs so they read as
          drafting marks — the vocabulary of a tender document — instead of glow.
        */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit]"
        >
          <div className="absolute top-0 right-0 size-64 opacity-40 [background-image:radial-gradient(#d4d4d8_1px,transparent_1px)] [background-size:16px_16px] [mask-image:linear-gradient(215deg,#000,transparent_72%)]" />
          <div className="absolute -right-28 -bottom-28 size-80 rounded-full border border-brand-100" />
          <div className="absolute -right-14 -bottom-14 size-52 rounded-full border border-brand-100/70" />
        </div>

        {/*
          The badge on the seam, drawn entirely with pseudo-elements: ::before is the
          white plate and ::after the red core inset inside it, so the rim follows the
          hexagon instead of sitting in a rounded box behind it. Two clip-paths and no
          SVG, no extra markup, nothing to give a unique id to.

          One transform serves both orientations. `-translate-x-1/2 -translate-y-1/2`
          centres the element on whatever point it is anchored to, so switching from
          the horizontal seam to the vertical one is only a change of anchor:
          top edge / horizontal centre on a phone, left edge / vertical centre from
          lg up. The transform itself never changes.

          The halo is on this wrapper and not on ::before, which is not a style
          preference — a filter is applied to an element *before* its own clip-path,
          so a drop-shadow declared next to the clip-path would be cast by the
          rectangle and then clipped away to nothing. Declared on the parent it is
          cast by the already-clipped child, and so takes the hexagon's shape.
        */}
        <span
          aria-hidden="true"
          className={[
            'pointer-events-none absolute z-20 flex items-center justify-center',
            'top-0 left-1/2 size-14 -translate-x-1/2 -translate-y-1/2',
            'lg:top-1/2 lg:left-0 lg:size-[72px]',
            'drop-shadow-[0_10px_26px_rgba(232,21,27,0.45)]',
            "before:absolute before:inset-0 before:content-['']",
            'before:bg-white before:[clip-path:polygon(50%_0%,93%_25%,93%_75%,50%_100%,7%_75%,7%_25%)]',
            "after:absolute after:inset-[5px] after:content-[''] lg:after:inset-[6px]",
            'after:[background-image:linear-gradient(135deg,var(--color-brand-400),var(--color-brand-700))]',
            'after:[clip-path:polygon(50%_0%,93%_25%,93%_75%,50%_100%,7%_75%,7%_25%)]',
          ].join(' ')}
        >
          <span className="relative z-10 text-white [&>svg]:size-5 lg:[&>svg]:size-6">
            {badge}
          </span>
        </span>

        {/*
          The only scrolling region on the page. `m-auto` on the child rather than
          `justify-center` on this container: auto margins centre the column while
          there is room to spare and collapse to nothing when there is not, whereas
          a centred flex child that outgrows its scroll container has its top pushed
          out of reach above the scroll origin.

          The vertical padding is measured in dvh rather than rem, so it gives back
          space on a short laptop instead of forcing a scrollbar and then wasting it
          again on a tall monitor. The ceiling stops the gap opening up absurdly at
          1440px.

          The mobile top floor is 2.25rem and not less because the badge hangs 28px
          down into the panel there; anything shorter and a scrolled registration
          form would run its first label under the hexagon. From lg the badge moves
          to the left edge and stops competing for that space, so the floor drops.
        */}
        <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-6 pt-[clamp(2.25rem,5dvh,3rem)] pb-[clamp(1.5rem,3.5dvh,2.5rem)] sm:px-10 lg:px-14 lg:pt-[clamp(1.5rem,4dvh,3rem)] xl:px-20">
          <div className={`m-auto w-full ${columnWidth}`}>
            {children}

            {/*
              The last line of the column, under whichever link the page ends on.
              text-xs against the text-sm above it is the whole hierarchy — no rule,
              no divider, no extra colour: this is boilerplate and should be the
              first thing the eye skips.

              neutral-500 rather than the neutral-400 it wore on the dark strip.
              400 is only 2.6:1 on white; 500 clears 4.8:1, and small print is
              exactly the text that cannot afford to be hard to read.

              It scrolls with the form on registration instead of holding still.
              That is the right trade: pinning it would mean a second scroll
              container to keep one sentence in view that nobody is looking for.
            */}
            <p className="mt-[clamp(1rem,2.5dvh,1.5rem)] text-center text-xs text-neutral-500">
              &copy; {new Date().getFullYear()} VR-Nexus. All rights reserved.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
