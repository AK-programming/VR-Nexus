/**
 * The card every panel on the dashboard is built from.
 *
 * One shell, so eight panels cannot end up with eight slightly different corner
 * radii and header paddings. `title` is rendered as an h2 because the page supplies
 * the h1.
 *
 * `collapsible` turns the header into an accordion toggle (a chevron + the title),
 * with the body shown or hidden by local state. It is opt-in and defaults off, so
 * every existing Panel renders exactly as before; only the callers that ask for it
 * get the toggle. The `action` slot stays OUTSIDE the toggle button, so a control in
 * the header (a Refresh button, a status chip) is clickable without collapsing the
 * panel.
 */

import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDownIcon } from '@/components/ui/icons'

type PanelProps = {
  title: string
  /** A second line under the title. Sets expectations; never repeats the title. */
  description?: string
  /** Top-right slot - a "View all" link or a range selector. */
  action?: ReactNode
  children: ReactNode
  /**
   * Drops the body padding so a divided list can run to the card's edges.
   */
  flush?: boolean
  /** Grid placement, supplied by the page. The panel never positions itself. */
  className?: string
  /** Turns the header into an accordion toggle. Off by default. */
  collapsible?: boolean
  /** Whether a collapsible panel starts open. Ignored when not collapsible. */
  defaultOpen?: boolean
}

export function Panel({
  title,
  description,
  action,
  children,
  flush = false,
  className,
  collapsible = false,
  defaultOpen = true,
}: PanelProps) {
  const [open, setOpen] = useState(defaultOpen)
  const bodyId = useId()
  const isOpen = collapsible ? open : true

  const heading = (
    <div className="min-w-0">
      <h2 className="font-display text-base font-semibold tracking-tight text-neutral-900">
        {title}
      </h2>
      {description ? <p className="mt-1 text-xs text-neutral-500">{description}</p> : null}
    </div>
  )

  return (
    <section
      className={[
        'flex min-w-0 flex-col overflow-hidden rounded-2xl border border-hairline bg-surface shadow-sm',
        className ?? '',
      ].join(' ')}
    >
      <div
        className={[
          'flex items-start justify-between gap-3 px-5 py-4',
          isOpen ? 'border-b border-hairline' : '',
        ].join(' ')}
      >
        {collapsible ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            aria-controls={bodyId}
            className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
          >
            <ChevronDownIcon
              aria-hidden="true"
              className={[
                'mt-0.5 size-4 shrink-0 text-neutral-400 transition-transform duration-150',
                open ? '' : '-rotate-90',
              ].join(' ')}
            />
            {heading}
          </button>
        ) : (
          heading
        )}
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>

      {isOpen ? (
        <div
          id={bodyId}
          className={flush ? 'flex min-h-0 flex-1 flex-col' : 'flex min-h-0 flex-1 flex-col p-5'}
        >
          {children}
        </div>
      ) : null}
    </section>
  )
}
