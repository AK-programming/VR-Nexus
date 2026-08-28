/**
 * Route guards.
 *
 * Both read the store rather than taking props, because a guard that has to be
 * handed the session is a guard someone can forget to hand it to.
 *
 * These are the client's half of authorisation and only the client's half. They
 * decide what to render; the API decides what a token is allowed to do. A guard
 * that passes still gets a 401 from the server if the token is stale, which is the
 * correct division — anything else would mean trusting a value the user can edit
 * in devtools.
 */

import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ROUTES } from '@/constants/routes'
import { selectIsAuthenticated, useAuthStore } from '@/store/authStore'

/**
 * Blocks a page until someone is signed in, and remembers where they were headed
 * so signing in returns them there instead of dumping them on the landing page.
 *
 * A session restored from storage counts as signed in here, before it has been
 * validated. That is deliberate: making every returning user wait on a network
 * round trip would put a spinner in front of the app on every single load, and if
 * the session turns out to be dead the store clears it and this guard redirects a
 * moment later.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const location = useLocation()

  if (!isAuthenticated) {
    return (
      <Navigate
        to={ROUTES.login}
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    )
  }

  return <>{children}</>
}

/**
 * Keeps a signed-in user off the sign-in and sign-up screens. Without this, the
 * back button after signing in lands on a login form that appears to have failed.
 *
 * Unlike RequireAuth, this one waits for the restored session to be verified. The
 * two are asymmetric on purpose, because the cost of being wrong is not the same:
 * showing the app to someone whose session has quietly expired means rendering
 * stale account data, while showing the sign-in form for the moment it takes to
 * check costs a redirect that fires a beat later. Somebody who deliberately opened
 * /login is also the most likely person to be holding a dead session.
 */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const isBootstrapping = useAuthStore((state) => state.isBootstrapping)

  if (isAuthenticated && !isBootstrapping) {
    return <Navigate to={ROUTES.home} replace />
  }

  return <>{children}</>
}

/**
 * Reads the path RequireAuth stashed, for the sign-in page to return to.
 *
 * The `startsWith('/')` check is not a formality: without it a crafted history
 * entry could send someone to another origin immediately after they signed in,
 * which is a textbook open redirect. Only same-origin paths are honoured.
 */
export function readReturnPath(state: unknown): string {
  if (state && typeof state === 'object' && 'from' in state) {
    const from = (state as { from?: unknown }).from

    if (typeof from === 'string' && from.startsWith('/') && !from.startsWith('//')) {
      return from
    }
  }

  return ROUTES.home
}
