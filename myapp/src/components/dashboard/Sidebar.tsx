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
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { formatInitials, formatRole } from '@/lib/formatting'
import type { FeatureKey, User } from '@/models'
import { BrandMark, BrandWordmark } from '@/components/ui/BrandMark'
import {
  ActivityIcon,
  BarChartIcon,
  CalculatorIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  FolderIcon,
  GridIcon,
  LockIcon,
  LogOutIcon,
  SettingsIcon,
  SparklesIcon,
  UsersIcon,
} from '@/components/ui/icons'

type NavLeaf = {
  to: string
  label: string
  icon: ComponentType<{ className?: string }>
  /** Only the dashboard needs it: without `end`, "/" matches every route. */
  end?: boolean
  /**
   * Gates the item behind a granted section. Omitted for items every signed-in
   * account can reach (Dashboard, Activity, Settings, Profile). An admin
   * always sees a gated item regardless of this key — see `visibleNavItems`
   * below — because `feature_access` is never consulted for an admin account,
   * on either side of the API.
   */
  feature?: FeatureKey
  /** Admin-only items (currently just Users, and the API Settings child
   * below) never check `feature` at all. */
  adminOnly?: boolean
}

/**
 * Settings is a dropdown, not a single link: "General settings" (every
 * account) and "API settings" (admin-only) live under one "Settings" entry
 * instead of API Settings sitting in the flat list as its own row — client
 * follow-up request, it "wasn't looking" right as a bare top-level item.
 * `children` is what distinguishes a group from a leaf in `NAV_ENTRIES`.
 */
type NavGroup = {
  label: string
  icon: ComponentType<{ className?: string }>
  children: NavLeaf[]
}

type NavEntry = NavLeaf | NavGroup

function isNavGroup(entry: NavEntry): entry is NavGroup {
  return 'children' in entry
}

/**
 * One flat, ordered list rather than three labelled groups (Workspace /
 * Account / Administration).
 *
 * Client follow-up request: the group headers and their extra vertical space
 * were pushing the last item (Users, for an admin) below the visible nav
 * area on shorter screens, with no way to reach it short of scrolling a
 * container that was clipping instead of scrolling. Flattening the list and
 * fixing the nav's overflow below both address that; keeping one list — and
 * a fixed order ending in API Usage, Activity, then Settings (now a
 * dropdown covering both General and API settings) — keeps it predictable
 * regardless of screen height or which sections happen to be granted.
 */
const NAV_ENTRIES: NavEntry[] = [
  { to: ROUTES.home, label: 'Dashboard', icon: GridIcon, end: true },
  { to: ROUTES.tenderAnalysis, label: 'Tender Analysis', icon: BarChartIcon, feature: 'tender_analysis' },
  /* `to` is fixed here; the actual href a user gets is resolved per-account in
     `visibleNavItems`, since an account with only `documents_upload` should
     land on Upload, not on a Library it cannot open. */
  { to: ROUTES.documents, label: 'Documents', icon: FolderIcon, feature: 'documents' },
  { to: ROUTES.assistant, label: 'AI Assistant', icon: SparklesIcon, feature: 'ai_assistant' },
  { to: ROUTES.adminUsers, label: 'Users', icon: UsersIcon, adminOnly: true },
  /* Not adminOnly: every signed-in account can open this, scoped to their
     own usage; only an admin sees everyone's — see ROUTES.apiUsage. */
  { to: ROUTES.apiUsage, label: 'API Usage', icon: CalculatorIcon },
  { to: ROUTES.activity, label: 'Activity', icon: ActivityIcon },
  {
    label: 'Settings',
    icon: SettingsIcon,
    children: [
      { to: ROUTES.settings, label: 'General settings', icon: SettingsIcon },
      { to: ROUTES.adminSettings, label: 'API settings', icon: LockIcon, adminOnly: true },
    ],
  },
]

/**
 * A fresh USER account starts with none of the gated sections — the client
 * suggestion this sidebar implements — so the filtering below is not an
 * optimisation, it is the only thing standing between a new sign-up and a
 * sidebar full of dead links to pages the API will 403 on the first request.
 * An admin is exempt from the filter entirely, matching `require_feature` on
 * the backend: role === admin always passes, feature_access is not read.
 *
 * Documents also gets its `to` rewritten here, per account: an account
 * granted only `documents_upload` (not the full `documents` view/manage
 * grant) is routed straight to the Upload screen, since the Library index it
 * would otherwise land on is guarded off and would just bounce it back out.
 *
 * A group (Settings) whose children are filtered down to exactly one entry
 * collapses into a plain leaf for that one child — a non-admin account has
 * nothing to pick between, so it gets a single "Settings" row that goes
 * straight to General settings, not a dropdown with one option in it.
 */
function visibleNavItems(user: User | null): NavEntry[] {
  const isAdmin = user?.role === 'admin'
  const granted = user?.feature_access ?? []
  const hasUploadOnly = !isAdmin && !granted.includes('documents') && granted.includes('documents_upload')

  const rewriteDocuments = (item: NavLeaf): NavLeaf =>
    item.to === ROUTES.documents && hasUploadOnly ? { ...item, to: ROUTES.documentsUpload } : item

  const visibleLeaf = (item: NavLeaf) =>
    item.adminOnly ? isAdmin : !item.feature || isAdmin || granted.includes(item.feature)

  const entries: NavEntry[] = []
  for (const entry of NAV_ENTRIES) {
    if (isNavGroup(entry)) {
      const children = entry.children.filter(visibleLeaf).map(rewriteDocuments)
      if (children.length === 0) continue
      if (children.length === 1) {
        entries.push({ ...children[0], label: entry.label, icon: entry.icon })
        continue
      }
      entries.push({ ...entry, children })
      continue
    }
    if (visibleLeaf(entry)) entries.push(rewriteDocuments(entry))
  }
  return entries
}

function NavItemLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavLeaf
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
          /* Client follow-up request: the selected item read as a faint white
             highlight with a pale-pink icon (brand-300, #ff938f) — not
             clearly "red." Now it's a red-tinted background (brand-500 at
             low alpha) with the icon in the same true brand red used for the
             left accent bar, so the active state reads as red at a glance,
             not just a slightly brighter row. */
          isActive
            ? 'bg-brand-500/15 text-white'
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
              isActive ? 'text-brand-500' : 'text-white/60 group-hover:text-white/90',
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

/**
 * The Settings dropdown: a toggle row (icon + label + chevron, not a link
 * itself) that expands into its children (General settings, API settings).
 * Starts expanded when the current URL is already one of its children's, so
 * following a direct link (or a refresh) to API Settings doesn't land the
 * admin on a collapsed group with no visible way to see where they are.
 *
 * Collapsed rail (`lg` icon-only): there's no room for an inline dropdown,
 * so the group renders as a plain link straight to its first child (General
 * settings) instead — same as any other icon in the rail. Expanding the
 * rail is how to reach API settings from there.
 */
function NavGroupLink({
  group,
  collapsed,
  onNavigate,
}: {
  group: NavGroup
  collapsed: boolean
  onNavigate: () => void
}) {
  const location = useLocation()
  const childActive = group.children.some((child) => location.pathname.startsWith(child.to))
  const [open, setOpen] = useState(childActive)
  const Icon = group.icon

  useEffect(() => {
    if (childActive) setOpen(true)
  }, [childActive])

  if (collapsed) {
    return <NavItemLink item={group.children[0]} collapsed={collapsed} onNavigate={onNavigate} />
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={[
          'group relative flex h-11 w-full items-center gap-3 rounded-xl px-3',
          'text-sm font-medium transition-colors duration-150',
          'focus-visible:outline-brand-300',
          childActive ? 'text-white' : 'text-white/70 hover:bg-white/[0.04] hover:text-white',
        ].join(' ')}
      >
        <Icon
          className={[
            'size-5 shrink-0 transition-colors duration-150',
            childActive ? 'text-brand-500' : 'text-white/60 group-hover:text-white/90',
          ].join(' ')}
        />
        <span className="flex-1 truncate text-left">{group.label}</span>
        <ChevronDownIcon
          className={[
            'size-4 shrink-0 text-white/50 transition-transform duration-150',
            open ? 'rotate-180' : '',
          ].join(' ')}
        />
      </button>
      {open ? (
        <div className="mt-1 flex flex-col gap-1 pl-8">
          {group.children.map((child) => (
            <NavItemLink key={child.label} item={child} collapsed={false} onNavigate={onNavigate} />
          ))}
        </div>
      ) : null}
    </div>
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
  const navItems = useMemo(() => visibleNavItems(user), [user])

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
          /* Slightly narrower than before (client follow-up request), on both the
             mobile drawer and the lg expanded rail — freeing enough height/width
             budget, combined with the flattened list below, that every item
             including Users fits without needing to scroll on ordinary screens. */
          'fixed inset-y-0 left-0 z-50 flex w-64 flex-col overflow-hidden bg-ink-950',
          'transition-[transform,visibility,width] duration-300 ease-out',
          open ? 'visible translate-x-0' : 'invisible -translate-x-full',
          'lg:visible lg:static lg:z-auto lg:shrink-0 lg:translate-x-0',
          /* Collapsed = a narrow icon rail; expanded = the full column. lg only. */
          collapsed ? 'lg:w-20' : 'lg:w-64',
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
            /* Mobile drawer is always this row layout, full width, regardless
               of `collapsed` — per this file's own invariant (see the header
               comment). At `lg` when collapsed, the row does not have room
               for the logo mark AND the toggle button side by side (the rail
               is only 80px wide): they used to fight for the same 60px of
               space and the toggle button got squeezed into the logo,
               reading as broken. The developer fix is to stop trying to fit
               both on one line there — stack them instead, centered, in
               their own small header block. */
            'relative flex h-16 shrink-0 items-center justify-between gap-2 px-5',
            collapsed
              ? 'lg:h-auto lg:flex-col lg:justify-center lg:gap-2 lg:px-2 lg:py-3'
              : '',
          ].join(' ')}
        >
          <Link
            to={ROUTES.home}
            onClick={onNavigate}
            className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-brand-300"
            aria-label="VR-Nexus dashboard"
          >
            <BrandMark className={collapsed ? 'h-6 w-auto shrink-0' : 'h-8 w-auto shrink-0'} />
            <span className={collapsed ? 'lg:hidden' : ''}>
              <BrandWordmark tone="light" />
            </span>
          </Link>

          {/* Collapse / expand. Top-right of the row when expanded; stacked
              below the logo, centered, when collapsed — its own line rather
              than crammed onto the logo's. lg only. */}
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

        {/* `overflow-y-auto` (not `overflow-hidden`) is the actual fix: on a short
            viewport or an account with every section granted, the list can still
            run taller than the rail — the Settings dropdown expanded included.
            Scrolling keeps every item reachable instead of clipped off the
            bottom the way Users was before this change. `overflow-x-hidden`
            keeps the focus ring on a fully-collapsed item from adding a
            horizontal scrollbar. */}
        <nav
          className={[
            'relative flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden py-4',
            collapsed ? 'lg:px-2' : 'px-3',
          ].join(' ')}
        >
          {navItems.map((item) =>
            isNavGroup(item) ? (
              <NavGroupLink key={item.label} group={item} collapsed={collapsed} onNavigate={onNavigate} />
            ) : (
              <NavItemLink key={item.label} item={item} collapsed={collapsed} onNavigate={onNavigate} />
            ),
          )}
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
