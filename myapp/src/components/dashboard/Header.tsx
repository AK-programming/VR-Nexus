/**
 * The top bar: a way into the rail on small screens, a working search, the one
 * primary action, a theme toggle, and a working notifications bell.
 *
 * Search and notifications both read the same two seams every screen uses
 * (`listTenders` + `listDocuments`); there is no dedicated search or notifications
 * endpoint yet, so both compose their result on the client and can be swapped for a
 * server feed later without changing this UI.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode, RefObject } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ROUTES, tenderDetailPath, documentViewerPath } from '@/constants/routes'
import { tenderTitle } from '@/models/tenders'
import type { TenderListItem } from '@/models/tenders'
import type { LibraryDocument } from '@/models/documents'
import { listTenders } from '@/services/tenderService'
import { listDocuments } from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { formatRelativeTime } from '@/lib/formatting'
import { useThemeStore } from '@/store/themeStore'
import { BrandMark, BrandWordmark } from '@/components/ui/BrandMark'
import { BRAND_SURFACE } from '@/components/ui/surfaces'
import {
  BellIcon,
  CheckCircleIcon,
  DatabaseIcon,
  MenuIcon,
  MoonIcon,
  PlusIcon,
  SearchIcon,
  SunIcon,
  XCircleIcon,
} from '@/components/ui/icons'

const ICON_BUTTON = [
  'flex size-10 shrink-0 items-center justify-center rounded-xl',
  'text-neutral-600 transition-colors duration-150',
  'hover:bg-surface-muted hover:text-neutral-900',
].join(' ')

const SEEN_KEY = 'vrnexus.notifications.seen'

type HeaderProps = {
  onOpenSidebar: () => void
  menuButtonRef: RefObject<HTMLButtonElement | null>
}

/* -------------------------------------------------------------------------- */
/* Theme toggle                                                               */
/* -------------------------------------------------------------------------- */

function ThemeToggle() {
  const resolved = useThemeStore((state) => state.resolved)
  const setTheme = useThemeStore((state) => state.setTheme)
  const goingDark = resolved !== 'dark'

  return (
    <button
      type="button"
      onClick={() => setTheme(goingDark ? 'dark' : 'light')}
      aria-label={goingDark ? 'Switch to dark theme' : 'Switch to light theme'}
      title={goingDark ? 'Dark theme' : 'Light theme'}
      className={ICON_BUTTON}
    >
      {goingDark ? <MoonIcon className="size-5" /> : <SunIcon className="size-5" />}
    </button>
  )
}

/* -------------------------------------------------------------------------- */
/* Search                                                                     */
/* -------------------------------------------------------------------------- */

type SearchHit = {
  id: string
  title: string
  subtitle: string
  kind: 'Tender' | 'Document'
  to: string
}

function useClickOutside(onOutside: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onOutside()
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onOutside])
  return ref
}

function HeaderSearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  /* Lazy: the library + tender lists are only read once the user actually uses
     search, so the header costs nothing on pages that never touch it. */
  const [activated, setActivated] = useState(false)

  const containerRef = useClickOutside(() => setOpen(false))

  const data = useAsyncData(
    async (signal) => {
      if (!activated) {
        return { tenders: [] as TenderListItem[], documents: [] as LibraryDocument[] }
      }
      const [tenders, documents] = await Promise.all([
        listTenders({ limit: 200 }, { signal }),
        listDocuments({}, { signal }),
      ])
      return { tenders, documents }
    },
    [activated],
  )

  const hits = useMemo<SearchHit[]>(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return []

    const out: SearchHit[] = []

    for (const t of data.data?.tenders ?? []) {
      const hay = `${tenderTitle(t)} ${t.original_filename} ${t.issuing_authority ?? ''}`.toLowerCase()
      if (hay.includes(needle)) {
        out.push({
          id: `t-${t.id}`,
          title: tenderTitle(t),
          subtitle: t.issuing_authority || t.original_filename,
          kind: 'Tender',
          to: tenderDetailPath(t.id),
        })
      }
    }

    for (const d of data.data?.documents ?? []) {
      const hay = `${d.title} ${d.original_filename} ${d.client} ${d.sector} ${d.keywords.join(' ')}`.toLowerCase()
      if (hay.includes(needle)) {
        out.push({
          id: `d-${d.id}`,
          title: d.title || d.original_filename,
          subtitle: d.client || d.sector || d.original_filename,
          kind: 'Document',
          to: documentViewerPath(d.id),
        })
      }
    }

    return out.slice(0, 8)
  }, [query, data.data])

  function goTo(to: string) {
    setOpen(false)
    setQuery('')
    navigate(to)
  }

  return (
    <div ref={containerRef} className="relative hidden min-w-0 flex-1 md:block md:max-w-md">
      <label htmlFor="workspace-search" className="sr-only">
        Search documents and tenders
      </label>
      <SearchIcon className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-neutral-500" />
      <input
        id="workspace-search"
        type="search"
        value={query}
        autoComplete="off"
        onFocus={() => {
          setActivated(true)
          setOpen(true)
        }}
        onChange={(event) => {
          setQuery(event.target.value)
          setOpen(true)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setOpen(false)
          } else if (event.key === 'Enter' && hits.length > 0) {
            goTo(hits[0].to)
          }
        }}
        placeholder="Search documents, tenders…"
        className="h-10 w-full rounded-xl border border-hairline bg-surface-muted pr-3 pl-10 text-sm text-neutral-900 transition-colors duration-150 placeholder:text-neutral-500 hover:border-neutral-300 focus:border-brand-400 focus:bg-surface focus:outline-none"
      />

      {open && query.trim() ? (
        <div className="absolute left-0 right-0 top-12 z-50 overflow-hidden rounded-xl border border-hairline bg-surface shadow-panel">
          {data.status === 'loading' ? (
            <p className="px-4 py-6 text-center text-sm text-neutral-500">Searching…</p>
          ) : hits.length === 0 ? (
            <p className="px-4 py-6 text-center text-sm text-neutral-500">
              Nothing matches “{query.trim()}”.
            </p>
          ) : (
            <ul className="max-h-80 divide-y divide-hairline overflow-y-auto">
              {hits.map((hit) => (
                <li key={hit.id}>
                  <button
                    type="button"
                    onClick={() => goTo(hit.to)}
                    className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left transition-colors hover:bg-surface-muted"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-neutral-900">
                        {hit.title}
                      </span>
                      <span className="block truncate text-xs text-neutral-500">
                        {hit.subtitle}
                      </span>
                    </span>
                    <span className="shrink-0 rounded-full bg-surface-muted px-2 py-0.5 text-[11px] font-medium text-neutral-500">
                      {hit.kind}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Notifications                                                              */
/* -------------------------------------------------------------------------- */

type Note = {
  id: string
  icon: ReactNode
  text: string
  at: string
  to: string
}

function NotificationsMenu() {
  const [open, setOpen] = useState(false)
  const [seenAt, setSeenAt] = useState<string>(() => {
    try {
      return localStorage.getItem(SEEN_KEY) ?? ''
    } catch {
      return ''
    }
  })

  const containerRef = useClickOutside(() => setOpen(false))

  const data = useAsyncData(
    async (signal) => {
      const [tenders, documents] = await Promise.all([
        listTenders({ limit: 200 }, { signal }),
        listDocuments({}, { signal }),
      ])
      return { tenders, documents }
    },
    [],
  )

  const notes = useMemo<Note[]>(() => {
    const out: Note[] = []

    for (const t of data.data?.tenders ?? []) {
      if (t.status === 'ready_for_review') {
        out.push({
          id: `t-ready-${t.id}`,
          icon: <CheckCircleIcon className="size-4 text-emerald-600" />,
          text: `Ready for review — ${tenderTitle(t)}`,
          at: t.failed_at ?? t.created_at,
          to: tenderDetailPath(t.id),
        })
      } else if (t.status === 'failed') {
        out.push({
          id: `t-failed-${t.id}`,
          icon: <XCircleIcon className="size-4 text-rose-500" />,
          text: `Analysis failed — ${tenderTitle(t)}`,
          at: t.failed_at ?? t.created_at,
          to: ROUTES.tenderProcessing,
        })
      }
    }

    for (const d of data.data?.documents ?? []) {
      if (d.training_status === 'indexed' && d.indexed_at) {
        out.push({
          id: `d-idx-${d.id}`,
          icon: <DatabaseIcon className="size-4 text-brand-600" />,
          text: `Indexed — ${d.title || d.original_filename}`,
          at: d.indexed_at,
          to: documentViewerPath(d.id),
        })
      }
    }

    out.sort((a, b) => b.at.localeCompare(a.at))
    return out.slice(0, 12)
  }, [data.data])

  const unread = useMemo(
    () => notes.filter((n) => n.at > seenAt).length,
    [notes, seenAt],
  )

  function toggle() {
    const next = !open
    setOpen(next)
    // Opening the panel marks everything seen, which clears the badge.
    if (next) {
      const now = new Date().toISOString()
      setSeenAt(now)
      try {
        localStorage.setItem(SEEN_KEY, now)
      } catch {
        /* best-effort */
      }
    }
  }

  const label =
    unread > 0 ? `Notifications, ${unread} unread` : 'Notifications, none unread'

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={toggle}
        aria-label={label}
        aria-expanded={open}
        className={`relative ${ICON_BUTTON}`}
      >
        <BellIcon className="size-5" />
        {unread > 0 ? (
          <span
            aria-hidden="true"
            className="absolute top-1.5 right-1.5 flex size-4 items-center justify-center rounded-full bg-brand-500 text-[0.625rem] font-semibold text-white ring-2 ring-surface"
          >
            {unread > 9 ? '9+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 top-12 z-50 w-80 overflow-hidden rounded-xl border border-hairline bg-surface shadow-panel">
          <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
            <span className="text-sm font-semibold text-neutral-900">Notifications</span>
            <span className="text-xs text-neutral-500">{notes.length} recent</span>
          </div>

          {data.status === 'loading' ? (
            <p className="px-4 py-8 text-center text-sm text-neutral-500">Loading…</p>
          ) : notes.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-neutral-500">
              Nothing needs your attention right now.
            </p>
          ) : (
            <ul className="max-h-96 divide-y divide-hairline overflow-y-auto">
              {notes.map((note) => (
                <li key={note.id}>
                  <Link
                    to={note.to}
                    onClick={() => setOpen(false)}
                    className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-muted"
                  >
                    <span className="mt-0.5 shrink-0">{note.icon}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm leading-snug text-neutral-800">
                        {note.text}
                      </span>
                      <span className="mt-0.5 block text-xs text-neutral-500 tabular-nums">
                        {formatRelativeTime(note.at)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <Link
            to={ROUTES.activity}
            onClick={() => setOpen(false)}
            className="block border-t border-hairline px-4 py-2.5 text-center text-xs font-medium text-brand-600 transition-colors hover:bg-surface-muted"
          >
            View all activity
          </Link>
        </div>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Header                                                                     */
/* -------------------------------------------------------------------------- */

export function Header({ onOpenSidebar, menuButtonRef }: HeaderProps) {
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

      <Link
        to={ROUTES.home}
        className="flex shrink-0 items-center gap-2.5 rounded-lg lg:hidden"
        aria-label="VR-Nexus dashboard"
      >
        <BrandMark className="h-7 w-auto" />
        <span className="hidden sm:block">
          <BrandWordmark tone="dark" />
        </span>
      </Link>

      <HeaderSearch />

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
          <span className="sr-only sm:not-sr-only">New Analysis</span>
        </Link>

        <ThemeToggle />
        <NotificationsMenu />
      </div>
    </header>
  )
}
