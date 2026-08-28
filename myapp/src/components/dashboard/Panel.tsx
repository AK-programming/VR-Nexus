/**
 * The card every panel on the dashboard is built from.
 *
 * One shell, so eight panels cannot end up with eight slightly different corner
 * radii and header paddings. The radius is `rounded-2xl` (16px) rather than the
 * theme's `--radius-panel` (40px) on purpose: that token belongs to the single
 * full-height sheet on the sign-in screen, and at the size of a dashboard card the
 * same curve eats the corners of the content.
 *
 * `title` is rendered as an h2 because the page supplies the h1. Nothing else in
 * the shell claims a heading level.
 */

import type { ReactNode } from 'react'

type PanelProps = {
  title: string
  /** A second line under the title. Sets expectations; never repeats the title. */
  description?: string
  /** Top-right slot — a "View all" link or a range selector. */
  action?: ReactNode
  children: ReactNode
  /**
   * Drops the body padding so a divided list can run to the card's edges. A list
   * with 20px of padding around it has rows that stop short of the divider above
   * them, which reads as a mistake rather than as breathing room.
   */
  flush?: boolean
  /** Grid placement, supplied by the page. The panel never positions itself. */
  className?: string
}

export function Panel({ title, description, action, children, flush = false, className }: PanelProps) {
  return (
    <section
      className={[
        'flex min-w-0 flex-col overflow-hidden rounded-2xl border border-hairline bg-surface shadow-sm',
        className ?? '',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
        <div className="min-w-0">
          <h2 className="font-display text-base font-semibold tracking-tight text-neutral-900">
            {title}
          </h2>
          {description ? <p className="mt-1 text-xs text-neutral-500">{description}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>

      {/* min-h-0 so a panel told to fill a tall grid row lets its own content
          scroll or shrink rather than pushing the card past its allotted height. */}
      <div className={flush ? 'flex min-h-0 flex-1 flex-col' : 'flex min-h-0 flex-1 flex-col p-5'}>
        {children}
      </div>
    </section>
  )
}
