/**
 * The top bar: a way into the rail on small screens, search, the one primary
 * action, notifications, and the account menu.
 *
 * It holds two pieces of local state and nothing else — the search text and
 * whether the account menu is open. Both are the header's own business; the
 * sidebar's open state is not, which is why that one lives in the parent and
 * arrives here as a single callback.
 *
 * The account menu is a disclosure, not an ARIA menu. `role="menu"` is a promise
 * that arrow keys move between items and Home/End jump to the ends, and a
 * disclosure that lies about that is worse for a keyboard user than one that
 * simply lets Tab do what Tab does. So: `aria-expanded`, `aria-controls`, Escape
 * to close, click-away to close, and ordinary focus order inside.
 */

import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { Link } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { formatInitials, formatRole } from '@/lib/formatting'
import type { User } from '@/models'
import { BrandMark, BrandWordmark } from '@/components/ui/BrandMark'
import { BRAND_SURFACE } from '@/components/ui/surfaces'
import {
  BellIcon,
  ChevronDownIcon,
  LogOutIcon,
  MenuIcon,
  PlusIcon,
  SearchIcon,
  SettingsIcon,
  UserCircleIcon,
} from '@/components/ui/icons'

/** Shared by the two icon-only buttons, so their hit areas match to the pixel. */
const ICON_BUTTON = [
  'flex size-10 shrink-0 items-center justify-center rounded-xl',
  'text-neutral-600 transition-colors duration-150',
  'hover:bg-surface-muted hover:text-neutral-900',
].join(' ')

type HeaderProps = {
  user: User | null
  /** Opens the rail. Only reachable below `lg`, where the button that calls it exists. */
  onOpenSidebar: () => void
  onSignOut: () => void
  unreadNotifications: number

  /**
   * Owned by the layout, attached here. The layout sends focus back to this button
   * when the drawer is dismissed, which it can only do if it holds the ref.
   */
  menuButtonRef: RefObject<HTMLButtonElement | null>
}

export function Header({
  user,
  onOpenSidebar,
  onSignOut,
  unreadNotifications,
  menuButtonRef,
}: HeaderProps) {
  const [query, setQuery] = useState('')
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  /*
   * Both listeners are attached only while the menu is open, so a closed menu costs
   * nothing. `pointerdown` rather than `click`: closing on the way down means the
   * menu is gone before a click on the page underneath resolves, which is what
   * makes dismissing it feel immediate rather than delayed by one frame.
   */
  useEffect(() => {
    if (!isMenuOpen) {
      return
    }

    function handlePointerDown(event: PointerEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsMenuOpen(false)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isMenuOpen])

  const notificationLabel =
    unreadNotifications > 0
      ? `Notifications, ${unreadNotifications} unread`
      : 'Notifications, none unread'

  return (
    <header className="flex h-16 shrink-0 items-center gap-2 border-b border-hairline bg-surface px-4 sm:gap-3 sm:px-6 lg:px-8">
      <button
        ref={menuButtonRef}
        type="button"
        onClick={onOpenSidebar}
        aria-label="Open navigation"
        className={`${ICON_BUTTON} lg:hidden`}
      >
        <MenuIcon className="size-5" />
      </button>

      {/* Identity, for the widths where the rail is hidden. From lg the rail is
          showing the same lockup two inches to the left. */}
      <Link
        to={ROUTES.home}
        className="flex shrink-0 items-center gap-2.5 rounded-lg lg:hidden"
        aria-label="VR-Nexus dashboard"
      >
        <BrandMark className="size-7 text-brand-500" />
        <span className="hidden sm:block">
          <BrandWordmark tone="dark" />
        </span>
      </Link>

      {/*
       * Search appears from md. Below that there is roughly 150px of free width
       * once the buttons are placed, and a search field that narrow is a field
       * nobody can read their own query in — Documents in the rail is the honest
       * route on a phone.
       */}
      <div className="relative hidden min-w-0 flex-1 md:block md:max-w-md">
        <label htmlFor="workspace-search" className="sr-only">
          Search documents, tenders and case studies
        </label>
        <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-neutral-500" />
        <input
          id="workspace-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search documents, tenders…"
          className="h-10 w-full rounded-xl border border-hairline bg-surface-muted pr-3 pl-10 text-sm text-neutral-900 transition-colors duration-150 placeholder:text-neutral-500 hover:border-neutral-300 focus:border-brand-400 focus:bg-surface"
        />
      </div>

      {/* ml-auto so the cluster stays right-aligned below md, where the flexible
          search field that would otherwise absorb the space is not rendered. */}
      <div className="ml-auto flex shrink-0 items-center gap-1.5 sm:gap-2">
        <Link
          to={ROUTES.tenderAnalysis}
          className={[
            'flex h-10 items-center justify-center gap-2 rounded-xl px-3 sm:px-4',
            'font-display text-sm font-semibold tracking-tight',
            'transition-all duration-200',
            BRAND_SURFACE,
          ].join(' ')}
        >
          <PlusIcon className="size-5 shrink-0" />
          {/* sr-only below sm rather than hidden: the label is still the button's
              accessible name when only the plus is visible, so the icon-only state
              is not an unnamed button. */}
          <span className="sr-only sm:not-sr-only">New Analysis</span>
        </Link>

        <button type="button" aria-label={notificationLabel} className={`relative ${ICON_BUTTON}`}>
          <BellIcon className="size-5" />
          {unreadNotifications > 0 ? (
            <span
              aria-hidden="true"
              className="absolute top-1.5 right-1.5 flex size-4 items-center justify-center rounded-full bg-brand-500 text-[0.625rem] font-semibold text-white ring-2 ring-surface"
            >
              {unreadNotifications > 9 ? '9+' : unreadNotifications}
            </span>
          ) : null}
        </button>

        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setIsMenuOpen((open) => !open)}
            aria-expanded={isMenuOpen}
            aria-controls="account-menu"
            className="flex h-10 items-center gap-2 rounded-xl pr-1.5 pl-1.5 transition-colors duration-150 hover:bg-surface-muted sm:pr-2.5"
          >
            <span
              aria-hidden="true"
              className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 font-display text-[0.6875rem] font-semibold text-brand-700"
            >
              {formatInitials(user?.name)}
            </span>
            <span className="hidden max-w-[9rem] truncate text-sm font-medium text-neutral-800 sm:block">
              {user?.name ?? 'Account'}
            </span>
            <ChevronDownIcon
              className={[
                'size-4 shrink-0 text-neutral-500 transition-transform duration-200',
                isMenuOpen ? 'rotate-180' : 'rotate-0',
              ].join(' ')}
            />
          </button>

          {isMenuOpen ? (
            <div
              id="account-menu"
              className="absolute top-full right-0 z-30 mt-2 w-64 overflow-hidden rounded-2xl border border-hairline bg-surface shadow-panel"
            >
              <div className="border-b border-hairline px-4 py-3">
                <p className="truncate text-sm font-semibold text-neutral-900">
                  {user?.name ?? 'Signed out'}
                </p>
                <p className="mt-0.5 truncate text-xs text-neutral-500">
                  {user?.email ?? 'No active session'}
                </p>
                {user ? (
                  <p className="mt-2 inline-flex items-center rounded-md bg-surface-muted px-2 py-0.5 text-[0.6875rem] font-medium tracking-wide text-neutral-600 uppercase">
                    {formatRole(user.role)}
                  </p>
                ) : null}
              </div>

              <div className="p-1.5">
                <Link
                  to={ROUTES.profile}
                  onClick={() => setIsMenuOpen(false)}
                  className="flex h-10 items-center gap-3 rounded-lg px-2.5 text-sm text-neutral-700 transition-colors hover:bg-surface-muted hover:text-neutral-900"
                >
                  <UserCircleIcon className="size-4 shrink-0 text-neutral-500" />
                  Your profile
                </Link>
                <Link
                  to={ROUTES.settings}
                  onClick={() => setIsMenuOpen(false)}
                  className="flex h-10 items-center gap-3 rounded-lg px-2.5 text-sm text-neutral-700 transition-colors hover:bg-surface-muted hover:text-neutral-900"
                >
                  <SettingsIcon className="size-4 shrink-0 text-neutral-500" />
                  Settings
                </Link>
              </div>

              <div className="border-t border-hairline p-1.5">
                {/* The only way out of the app. Deliberately not repeated in the
                    rail — two sign-out controls invite the question of whether
                    they do the same thing. */}
                <button
                  type="button"
                  onClick={() => {
                    setIsMenuOpen(false)
                    onSignOut()
                  }}
                  className="flex h-10 w-full items-center gap-3 rounded-lg px-2.5 text-sm font-medium text-brand-600 transition-colors hover:bg-brand-50"
                >
                  <LogOutIcon className="size-4 shrink-0" />
                  Sign out
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  )
}
