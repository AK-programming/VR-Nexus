/**
 * The shell every signed-in screen lives inside, and the only component that knows
 * the whole layout.
 *
 * It owns exactly one piece of state — whether the navigation drawer is open —
 * because that is the one thing no single child can decide: the header's button
 * opens it, the rail's own close button and scrim shut it, a link inside it shuts
 * it on the way out, and Escape shuts it from anywhere. State that four children
 * touch belongs to their parent.
 *
 * Everything else is delegated. The header keeps its own search text and account
 * menu, the rail keeps nothing, the footer keeps nothing, and the page in the
 * middle is whatever the router put there.
 *
 * Structurally: a flex row, always. Below `lg` the rail is `position: fixed` and so
 * out of flow, leaving the content column as the row's only child and full width;
 * from `lg` the rail becomes `static` and takes its 280px as a normal flex item.
 * One layout, no duplicated tree, no `lg:pl-[17.5rem]` compensating for a fixed
 * element that is only sometimes fixed.
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Footer } from '@/components/dashboard/Footer'
import { Header } from '@/components/dashboard/Header'
import { Sidebar } from '@/components/dashboard/Sidebar'
import { useAuthStore } from '@/store/authStore'

type DashboardLayoutProps = {
  /**
   * The page. Optional so the component works either way: the router mounts it as
   * a layout route and lets `<Outlet />` fill this in, but passing a child directly
   * is useful for a one-off screen that is not part of the nested route tree.
   */
  children?: ReactNode
}

export function DashboardLayout({ children }: DashboardLayoutProps) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  /* Whether the lg rail is collapsed to an icon strip. Persisted per browser so a
     user who prefers the narrow rail keeps it across visits. Wrapped in try/catch
     because private windows can throw on storage access. */
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('vrnexus.sidebar.collapsed') === '1'
    } catch {
      return false
    }
  })

  function toggleSidebarCollapsed() {
    setIsSidebarCollapsed((current) => {
      const next = !current
      try {
        localStorage.setItem('vrnexus.sidebar.collapsed', next ? '1' : '0')
      } catch {
        /* best-effort */
      }
      return next
    })
  }

  /* Held here rather than in the header so focus can be sent back to the control
     that opened the drawer when the drawer is dismissed. Without it, dismissing
     with Escape drops focus onto <body> and the next Tab starts from the top of
     the document — a keyboard user would have to walk the whole header again. */
  const menuButtonRef = useRef<HTMLButtonElement>(null)

  /* The one scrolling element (see below). Held so navigation can reset it to the
     top: the shell is mounted once and survives route changes, so without this a
     new page opens at wherever the previous page was scrolled to. */
  const scrollRef = useRef<HTMLDivElement>(null)

  const location = useLocation()

  /* One field per selector. Zustand v5 compares with Object.is, so selecting
     `{ user, logout }` would build a new object every call and re-render on every
     unrelated store change. */
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  /** Dismissal: the scrim, the rail's close button, Escape. Focus goes back. */
  function dismissSidebar() {
    setIsSidebarOpen(false)
    menuButtonRef.current?.focus()
  }

  /** Leaving via a link. The destination gets focus attention, not the hamburger. */
  function closeSidebarQuietly() {
    setIsSidebarOpen(false)
  }

  /* Covers the routes a link inside the rail does not: browser back and forward,
     and any navigation triggered in code. Cheap insurance against the drawer
     surviving a route change and covering the page the user just asked for. */
  useEffect(() => {
    setIsSidebarOpen(false)
    /* Every screen opens at the top. `scrollTop = 0` rather than
       window.scrollTo, because the window never scrolls here — this inner box is
       the only scroller. Keyed on pathname so it fires on each navigation but not
       on a same-page state change (a filter, a dialog) the user is mid-scroll in. */
    scrollRef.current?.scrollTo({ top: 0 })
  }, [location.pathname])

  useEffect(() => {
    if (!isSidebarOpen) {
      return
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsSidebarOpen(false)
        menuButtonRef.current?.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isSidebarOpen])

  return (
    <div className="flex h-dvh overflow-hidden bg-surface-muted">
      <Sidebar
        open={isSidebarOpen}
        onClose={dismissSidebar}
        onNavigate={closeSidebarQuietly}
        onSignOut={logout}
        user={user}
        collapsed={isSidebarCollapsed}
        onToggleCollapse={toggleSidebarCollapsed}
      />

      {/* The content column. min-w-0 so a wide table or a long unbroken filename
          inside a panel cannot force the flex row wider than the window. */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Header
          menuButtonRef={menuButtonRef}
          onOpenSidebar={() => setIsSidebarOpen(true)}
        />

        {/*
         * The only scrolling element on the page. The header stays put because it is
         * a sibling of this box rather than a child of it, which is cheaper and
         * steadier than `sticky` — there is no scroll position for it to react to.
         *
         * min-h-0 is doing real work: without it this flex child takes its content's
         * height as its minimum and grows the whole shell past `h-dvh` instead of
         * scrolling inside it.
         */}
        <div ref={scrollRef} className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">
          {/* flex-1 pushes the footer to the bottom of a short page and lets it fall
              naturally below the fold on a long one. */}
          <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8">{children ?? <Outlet />}</main>
          <Footer />
        </div>
      </div>
    </div>
  )
}
