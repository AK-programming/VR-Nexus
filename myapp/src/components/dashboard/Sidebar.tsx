/**
 * The primary navigation rail.
 *
 * One component, three behaviours. Below `lg` it is an off-canvas drawer over a
 * scrim (`open`). From `lg` it is a fixed column that is either full width (labels
 * shown) or collapsed to an icon rail (`collapsed`), toggled by the chevron in its
 * header and remembered across sessions by the layout.
 *
 * It is dark in BOTH themes (it shares the sign-in panel's surface), so its text
 * must NOT use the `text-neutral-*` scale: that scale inverts under
 * `[data-theme="dark"]`, which turned the labels dark-on-dark and invisible in
 * dark mode. Everything here uses fixed white-alpha instead, so the rail looks the
 * same light-on-dark in either theme.
 *
 * Collapse is an `lg:`-only concern: every collapsed style is `lg:`-prefixed, so
 * the mobile drawer is always the full labelled rail regardless of `collapsed`.
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
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  FolderIcon,
  GridIcon,
  LogOutIcon,
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

function NavGroupLabel({ children, collapsed }: { children: string; collapsed: boolean }) {
  return (
    <p
      className={[
        'px-3 pb-2 text-[0.6875rem] font-semibold tracking-[0.16em] text-white/40 uppercase',
        collapsed ? 'lg:hidden' : '',
      ].join(' ')}
    >
      {children}
    </p>
  )
}

function NavItemLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  onNavigate: () => void
}) {
  const Icon = item.icon

  return (
    <NavLink
      to={item.to}
      end={item.end}
      onClick={onNavigate}
      /* The label is also the tooltip, so a collapsed icon rail still says what
         each icon is on hover. */
      title={item.label}
      className={({ isActive }) =>
        [
          'group relative flex h-11 items-center gap-3 rounded-xl px-3',
          'text-sm font-medium transition-colors duration-150',
          'focus-visible:outline-brand-300',
          collapsed ? 'lg:justify-center lg:px-0' : '',
          isActive
            ? 'bg-white/[0.07] text-white'
            : 'text-white/70 hover:bg-white/[0.04] hover:text-white',
        ].join(' ')
      }
    >
      {({ isActive }) => (
        <>
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
              isActive ? 'text-brand-300' : 'text-white/60 group-hover:text-white/90',
            ].join(' ')}
          />
          <span className={['truncate', collapsed ? 'lg:hidden' : ''].join(' ')}>
            {item.label}
          </span>
        </>
      )}
    </NavLink>
  )
}

type SidebarProps = {
  open: boolean
  onClose: () => void
  onNavigate: () => void
  onSignOut: () => void
  user: User | null
  /** lg-only: collapsed to an icon rail. Ignored below lg (always the full drawer). */
  collapsed: boolean
  /** Toggles `collapsed`. The chevron in the rail header calls it. */
  onToggleCollapse: () => void
}

export function Sidebar({
  open,
  onClose,
  onNavigate,
  onSignOut,
  user,
  collapsed,
  onToggleCollapse,
}: SidebarProps) {
  const roleLabel = formatRole(user?.role)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (open) {
      closeButtonRef.current?.focus()
    }
  }, [open])

  return (
    <>
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
          'transition-[transform,visibility,width] duration-300 ease-out',
          open ? 'visible translate-x-0' : 'invisible -translate-x-full',
          'lg:visible lg:static lg:z-auto lg:shrink-0 lg:translate-x-0',
          /* Collapsed = a narrow icon rail; expanded = the full column. lg only. */
          collapsed ? 'lg:w-[5.25rem]' : 'lg:w-[17.5rem]',
        ].join(' ')}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(120%_80%_at_50%_0%,rgba(232,21,27,0.3),transparent_70%)]"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-y-0 right-0 w-px bg-white/10"
        />

        <div
          className={[
            'relative flex h-16 shrink-0 items-center justify-between gap-2',
            collapsed ? 'lg:px-2.5' : 'px-5',
          ].join(' ')}
        >
          <Link
            to={ROUTES.home}
            onClick={onNavigate}
            className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-brand-300"
            aria-label="VR-Nexus dashboard"
          >
            <BrandMark className={collapsed ? 'h-7 w-auto shrink-0' : 'h-8 w-auto shrink-0'} />
            <span className={collapsed ? 'lg:hidden' : ''}>
              <BrandWordmark tone="light" />
            </span>
          </Link>

          {/* Collapse / expand — icon only, top-right, the standard placement. lg only. */}
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            title={collapsed ? 'Expand' : 'Collapse'}
            className="hidden size-8 shrink-0 items-center justify-center rounded-lg text-white/60 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-brand-300 lg:flex"
          >
            {collapsed ? (
              <ChevronRightIcon className="size-5" />
            ) : (
              <ChevronLeftIcon className="size-5" />
            )}
          </button>

          {/* Mobile drawer close. */}
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close navigation"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-brand-300 lg:hidden"
          >
            <CloseIcon className="size-5" />
          </button>
        </div>

        <nav
          className={[
            'relative flex min-h-0 flex-1 flex-col gap-6 overflow-hidden py-4',
            collapsed ? 'lg:px-2' : 'px-3',
          ].join(' ')}
        >
          <div className="flex flex-col gap-1">
            <NavGroupLabel collapsed={collapsed}>Workspace</NavGroupLabel>
            {WORKSPACE_ITEMS.map((item) => (
              <NavItemLink key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </div>

          <div className="flex flex-col gap-1">
            <NavGroupLabel collapsed={collapsed}>Account</NavGroupLabel>
            {ACCOUNT_ITEMS.map((item) => (
              <NavItemLink key={item.to} item={item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </div>
        </nav>

        <div
          className={[
            'relative flex shrink-0 items-center gap-2 border-t border-white/10 p-3',
            collapsed ? 'lg:flex-col lg:gap-3' : '',
          ].join(' ')}
        >
          <Link
            to={ROUTES.profile}
            onClick={onNavigate}
            title={user?.name ?? 'Profile'}
            className={[
              'flex min-w-0 flex-1 items-center gap-3 rounded-xl p-2 transition-colors',
              'hover:bg-white/[0.06] focus-visible:outline-brand-300',
              collapsed ? 'lg:flex-none lg:justify-center lg:p-1' : '',
            ].join(' ')}
          >
            <span
              aria-hidden="true"
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-500/20 font-display text-xs font-semibold text-brand-200"
            >
              {formatInitials(user?.name)}
            </span>
            <span className={['flex min-w-0 flex-col', collapsed ? 'lg:hidden' : ''].join(' ')}>
              <span className="truncate text-sm font-medium text-white">
                {user?.name ?? 'Signed out'}
              </span>
              <span className="truncate text-xs text-white/50">
                {roleLabel || 'No active session'}
              </span>
            </span>
          </Link>
          <button
            type="button"
            onClick={onSignOut}
            aria-label="Sign out"
            title="Sign out"
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-brand-300"
          >
            <LogOutIcon className="size-4" />
          </button>
        </div>
      </aside>
    </>
  )
}
