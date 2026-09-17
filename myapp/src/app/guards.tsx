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
import type { FeatureKey } from '@/models'
import { selectIsAdmin, selectIsAuthenticated, useAuthStore } from '@/store/authStore'

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
 * Blocks a page behind RequireAuth from anyone whose account is not an
 * admin — the Users page's own guard, since it lists every account and lets
 * an admin edit what each one can reach.
 *
 * Deliberately sends a non-admin to the dashboard rather than to sign-in:
 * they are signed in, they are just not allowed here, and bouncing them to
 * the login form would look like a broken session rather than a permissions
 * boundary.
 *
 * This is still only the client's half of the check — see the file
 * docstring above. `require_role(UserRole.ADMIN)` on every /api/admin/*
 * route is what actually stops a non-admin from reaching the data; this
 * guard only stops them from seeing the screen that would ask for it.
 */
export function RequireAdmin({ children }: { children: ReactNode }) {
  const isAdmin = useAuthStore(selectIsAdmin)

  if (!isAdmin) {
    return <Navigate to={ROUTES.home} replace />
  }

  return <>{children}</>
}

/**
 * Blocks a page behind RequireAuth from an account that has not been granted
 * the section it belongs to — client follow-up request: Tender Tools has to
 * genuinely require access rather than just existing as an unenforced
 * checkbox, and Documents needs to accept either the full `documents` grant
 * or the narrower `documents_upload` one depending on the route.
 *
 * `feature` takes either one key or several. With several, `requireAll`
 * chooses AND vs OR: Tender Tools passes `['tender_analysis','tender_tools']`
 * with `requireAll` (it needs both, since the tools reuse tender data), while
 * a Documents upload route passes `['documents','documents_upload']` without
 * it (either grant is enough to reach that one screen).
 *
 * An admin always passes, before `feature` is even looked at — the same
 * unconditional bypass `require_feature` on the backend and `RequireAdmin`
 * both use, so this guard never disagrees with the server about what an
 * admin can reach.
 *
 * Sends a denied user to the dashboard, not to sign-in, for the same reason
 * `RequireAdmin` does: they are signed in, just not granted this section.
 */
export function RequireFeature({
  feature,
  requireAll = false,
  children,
}: {
  feature: FeatureKey | FeatureKey[]
  requireAll?: boolean
  children: ReactNode
}) {
  const isAdmin = useAuthStore(selectIsAdmin)
  const featureAccess = useAuthStore((state) => state.user?.feature_access ?? [])

  if (!isAdmin) {
    const required = Array.isArray(feature) ? feature : [feature]
    const isGranted = requireAll
      ? required.every((key) => featureAccess.includes(key))
      : required.some((key) => featureAccess.includes(key))

    if (!isGranted) {
      return <Navigate to={ROUTES.home} replace />
    }
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
