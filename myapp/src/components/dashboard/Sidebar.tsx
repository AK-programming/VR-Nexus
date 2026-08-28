/**
 * The primary navigation rail.
 *
 * One component, two behaviours, decided entirely by breakpoint: below `lg` it is
 * an off-canvas drawer over a scrim, from `lg` it is a fixed 280px column that is
 * always there. `open` is meaningless from `lg` up, which is why the classes for
 * it are all unprefixed and every `lg:` class overrides them.
 *
 * `invisible` rather than only `-translate-x-full` when closed: a panel pushed off
 * the left edge is still in the tab order, so a keyboard user would tab into eight
 * links they cannot see. `visibility: hidden` takes it out of both the tab order
 * and the accessibility tree, and still animates, because visibility interpolates
 * in discrete steps rather than being dropped from the transition.
 *
 * It is dark for the same reason the sign-in panel is dark — the rail and the
 * brand side of the auth screen are the same surface, so signing in reads as
 * moving further into one product rather than arriving at a different one.
 */

import type { ComponentType } from 'react'
import { useEffect, useRef } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { formatInitials, formatRole } from '@/lib/formatting'
import type { User } from '@/models'
import { BrandMark, BrandWordmark } from '@/components/ui/BrandMark'
import {
  ActivityIcon,
  BarChartIcon,
  CloseIcon,
  FolderIcon,
  GridIcon,
  SettingsIcon,
  SparklesIcon,
} from '@/components/ui/icons'

type NavItem = {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  /** Only the dashboard needs it: without `end`, "/" matches every route. */
  end?: boolean
}

/*
 * Two groups, because the split is real rather than decorative: the first is work
 * on tenders, the second is the account doing the work. A single flat list of six
 * would make "Settings" look like a sixth kind of analysis.
 */
const WORKSPACE_ITEMS: NavItem[] = [
  { to: ROUTES.home, label: 'Dashboard', icon: GridIcon, end: true },
  { to: ROUTES.tenderAnalysis, label: 'Tender Analysis', icon: BarChartIcon },
  { to: ROUTES.documents, label: 'Documents', icon: FolderIcon },
  { to: ROUTES.assistant, label: 'AI Assistant', icon: SparklesIcon },
]

const ACCOUNT_ITEMS: NavItem[] = [
  { to: ROUTES.activity, label: 'Activity', icon: ActivityIcon },
  { to: ROUTES.settings, label: 'Settings', icon: SettingsIcon },
]

/**
 * Section heading. A paragraph, not a heading element: the page's outline is h1
 * for the screen and h2 for each panel, and two group labels in the rail would
 * insert themselves into that outline claiming to be peers of "Recent Projects".
 * The rail is already named by the aside's aria-label; these are visual grouping.
 */
function NavGroupLabel({ children }: { children: string }) {
  return (
    <p className="px-3 pb-2 text-[0.6875rem] font-semibold tracking-[0.16em] text-neutral-400 uppercase">
      {children}
    </p>
  )
}

function NavItemLink({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const Icon = item.icon

  return (
    <NavLink
      to={item.to}
      end={item.end}
      /* Closes the drawer on the way out. Harmless from lg up, where there is no
         drawer to close, and it saves branching on the breakpoint in JS. */
      onClick={onNavigate}
      className={({ isActive }) =>
        [
          'group relative flex h-11 items-center gap-3 rounded-xl px-3',
          'text-sm font-medium transition-colors duration-150',
          'focus-visible:outline-brand-300',
          isActive
            ? 'bg-white/[0.07] text-white'
            : 'text-neutral-300 hover:bg-white/[0.04] hover:text-white',
        ].join(' ')
      }
    >
      {({ isActive }) => (
        <>
          {/* The active marker. A bar on the leading edge, not a colour change
              alone — colour is the first thing to go on a bad screen. */}
          <span
            aria-hidden="true"
            className={[
              'absolute top-1/2 left-0 h-5 w-[3px] -translate-y-1/2 rounded-r-full',
              'bg-brand-500 transition-opacity duration-150',
              isActive ? 'opacity-100' : 'opacity-0',
            ].join(' ')}
          />
          <Icon
            className={[
              'size-5 shrink-0 transition-colors duration-150',
              isActive ? 'text-brand-300' : 'text-neutral-400 group-hover:text-neutral-200',
            ].join(' ')}
          />
          <span className="truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

type SidebarProps = {
  /** Drawer state. Ignored from `lg` up, where the rail is permanent. */
  open: boolean
  /** Dismissal — the scrim and the close button. Returns focus to the trigger. */
  onClose: () => void
  /** Leaving by link. Shuts the drawer without pulling focus back to the header. */
  onNavigate: () => void
  user: User | null
}

export function Sidebar({ open, onClose, onNavigate, user }: SidebarProps) {
  const roleLabel = formatRole(user?.role)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  /*
   * Focus follows the drawer in. Opening a panel over the page and leaving focus
   * behind it means the first Tab lands on something the reader cannot see.
   *
   * This is not a focus trap. A trap is the right answer for a modal dialog, and
   * this is a navigation drawer with a scrim, an Escape handler and a visible close
   * button — Tab reaching the page behind it is survivable, and a hand-rolled trap
   * that gets an edge case wrong is not. If this ever becomes a true dialog, the
   * trap goes in with it rather than being approximated here.
   */
  useEffect(() => {
    if (open) {
      closeButtonRef.current?.focus()
    }
  }, [open])

  return (
    <>
      {/* Scrim. Rendered only while open, so it cannot swallow clicks when closed. */}
      {open ? (
        <div
          className="fixed inset-0 z-40 bg-ink-950/70 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      ) : null}

      <aside
        aria-label="Main navigation"
        className={[
          'fixed inset-y-0 left-0 z-50 flex w-[17.5rem] flex-col overflow-hidden bg-ink-950',
          'transition-[transform,visibility] duration-300 ease-out',
          open ? 'visible translate-x-0' : 'invisible -translate-x-full',
          /* From lg it stops being a drawer entirely: a flex child of the shell,
             always visible, no transform, and no animation left to fire on resize. */
          'lg:visible lg:static lg:z-auto lg:shrink-0 lg:translate-x-0 lg:transition-none',
        ].join(' ')}
      >
        {/* Ambience, not an image. The sign-in page's cityscape is a portrait crop
            with the wordmark baked into it, so any slice of it here would look
            wrong; this is the same red light without the photograph. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(120%_80%_at_50%_0%,rgba(232,21,27,0.3),transparent_70%)]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 w-px bg-white/10"
        />

        <div className="relative flex h-16 shrink-0 items-center justify-between gap-3 px-5">
          <Link
            to={ROUTES.home}
            onClick={onNavigate}
            className="flex items-center gap-3 rounded-lg focus-visible:outline-brand-300"
          >
            <BrandMark className="size-8 shrink-0 text-brand-500" />
            <BrandWordmark tone="light" />
          </Link>

          {/* Only exists while the rail is a drawer. */}
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-neutral-300 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-brand-300 lg:hidden"
          >
            <CloseIcon className="size-5" />
          </button>
        </div>

        {/* The scrolling middle. min-h-0 so it shrinks instead of pushing the
            identity card off the bottom of a short window. */}
        <nav className="relative flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto overscroll-contain px-3 py-4">
          <div className="flex flex-col gap-1">
            <NavGroupLabel>Workspace</NavGroupLabel>
            {WORKSPACE_ITEMS.map((item) => (
              <NavItemLink key={item.to} item={item} onNavigate={onNavigate} />
            ))}
          </div>

          <div className="flex flex-col gap-1">
            <NavGroupLabel>Account</NavGroupLabel>
            {ACCOUNT_ITEMS.map((item) => (
              <NavItemLink key={item.to} item={item} onNavigate={onNavigate} />
            ))}
          </div>
        </nav>

        {/* Identity, and a way to edit it. Signing out lives in the header menu
            instead — one exit, not two, so nobody has to work out whether the two
            do the same thing. */}
        <div className="relative shrink-0 border-t border-white/10 p-3">
          <Link
            to={ROUTES.profile}
            onClick={onNavigate}
            className="flex items-center gap-3 rounded-xl p-2 transition-colors hover:bg-white/[0.06] focus-visible:outline-brand-300"
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-500/20 font-display text-xs font-semibold text-brand-200"
            >
              {formatInitials(user?.name)}
            </span>
            <span className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-medium text-white">
                {user?.name ?? 'Signed out'}
              </span>
              <span className="truncate text-xs text-neutral-400">
                {roleLabel || 'No active session'}
              </span>
            </span>
          </Link>
        </div>
      </aside>
    </>
  )
}
