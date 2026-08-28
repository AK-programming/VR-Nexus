/**
 * Temporary landing page.
 *
 * It exists so the auth flow can be verified end to end: sign in, land here, see
 * that the session survives a refresh, sign out again. It reads the user straight
 * from the store, which is the same path every real page will use.
 *
 * Delete this file when the workspace is built and point ROUTES.home at that
 * instead. Nothing else imports it.
 */

import { Navigate } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { useAuthStore } from '@/store/authStore'

export function HomePage() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  /* RequireAuth already guarantees a user, so this only narrows the type — but if
     the guard is ever removed, the page redirects rather than crashing. */
  if (!user) {
    return <Navigate to={ROUTES.login} replace />
  }

  return (
    <main className="mx-auto flex min-h-svh max-w-2xl flex-col justify-center px-6 py-16">
      <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
        Signed in
      </p>
      <h1 className="mt-3 font-display text-3xl font-semibold tracking-tight text-neutral-900">
        {user.name}
      </h1>

      <dl className="mt-8 divide-y divide-hairline border-y border-hairline text-sm">
        <div className="flex items-baseline justify-between gap-6 py-3">
          <dt className="text-neutral-500">Email</dt>
          <dd className="text-neutral-900">{user.email}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-6 py-3">
          <dt className="text-neutral-500">Role</dt>
          <dd className="text-neutral-900 capitalize">{user.role}</dd>
        </div>
        <div className="flex items-baseline justify-between gap-6 py-3">
          <dt className="text-neutral-500">Last sign-in</dt>
          <dd className="text-neutral-900">
            {user.last_login_at
              ? new Date(user.last_login_at).toLocaleString()
              : 'This is your first'}
          </dd>
        </div>
      </dl>

      <p className="mt-8 text-sm leading-relaxed text-neutral-500">
        Authentication is wired up. The workspace replaces this page.
      </p>

      <button
        type="button"
        onClick={logout}
        className="mt-6 inline-flex h-11 items-center self-start rounded-xl border border-hairline bg-surface px-4 font-display text-sm font-semibold text-neutral-700 transition-colors hover:border-neutral-300 hover:bg-surface-muted hover:text-neutral-900"
      >
        Sign out
      </button>
    </main>
  )
}
