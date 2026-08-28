/**
 * The "View all" link that sits in a panel's header.
 *
 * Its own file because three panels use it and a link that is styled slightly
 * differently in each one is how a page starts to look assembled rather than
 * designed. The chevron leads rather than discloses, which is why it is
 * ChevronRight and not ChevronDown.
 */

import { Link } from 'react-router-dom'
import { ChevronRightIcon } from '@/components/ui/icons'

type PanelLinkProps = {
  to: string
  children: string
}

export function PanelLink({ to, children }: PanelLinkProps) {
  return (
    <Link
      to={to}
      className="group flex items-center gap-1 rounded-lg text-sm font-medium text-brand-600 transition-colors hover:text-brand-700"
    >
      {children}
      {/* Nudges forward on hover. One property, 150ms — enough to acknowledge the
          pointer without turning a link into an event. */}
      <ChevronRightIcon className="size-4 transition-transform duration-150 group-hover:translate-x-0.5" />
    </Link>
  )
}
