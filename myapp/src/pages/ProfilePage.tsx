/**
 * Profile - who you are in this workspace.
 *
 * Read-only for now (there is no profile-update endpoint yet), but a designed
 * screen rather than a placeholder: the account card mirrors the one in Settings,
 * with the identity, an avatar, and the honest note that editing is on the way.
 * Sign-out lives in the sidebar footer now, so the copy points there rather than
 * to the old header menu.
 */

import { ROUTES } from '@/constants/routes'
import { formatInitials, formatRole } from '@/lib/formatting'
import { useAuthStore } from '@/store/authStore'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { GridIcon, LogOutIcon, SettingsIcon } from '@/components/ui/icons'

export function ProfilePage() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
          Your profile
        </h1>
        <p className="mt-1 text-sm text-neutral-500">
          Your account details in this workspace.
        </p>
      </header>

      <Panel title="Account" description="This is how VR-Nexus identifies you.">
        <div className="flex items-center gap-4">
          <span
            aria-hidden="true"
            className="flex size-14 shrink-0 items-center justify-center rounded-2xl bg-brand-50 font-display text-lg font-semibold text-brand-700"
          >
            {formatInitials(user?.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-base font-semibold text-neutral-900">
              {user?.name ?? 'Signed out'}
            </p>
            <p className="truncate text-sm text-neutral-500">{user?.email ?? 'No active session'}</p>
          </div>
        </div>

        <dl className="mt-5 flex flex-col divide-y divide-hairline border-t border-hairline">
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Role</dt>
            <dd className="text-sm font-medium text-neutral-900">{formatRole(user?.role) || '-'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Name</dt>
            <dd className="text-sm font-medium text-neutral-900">{user?.name ?? '-'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Email</dt>
            <dd className="truncate text-sm font-medium text-neutral-900">{user?.email ?? '-'}</dd>
          </div>
        </dl>

        <p className="mt-4 rounded-xl border border-hairline bg-surface-muted px-3.5 py-3 text-xs leading-relaxed text-neutral-600">
          Editing your name, phone number and company is coming. You can sign out from the account
          card at the bottom of the sidebar, and change your theme in Settings.
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          <ActionButton variant="secondary" size="sm" to={ROUTES.home} leadingIcon={<GridIcon />}>
            Back to dashboard
          </ActionButton>
          <ActionButton variant="secondary" size="sm" to={ROUTES.settings} leadingIcon={<SettingsIcon />}>
            Settings
          </ActionButton>
          <ActionButton variant="danger" size="sm" onClick={logout} leadingIcon={<LogOutIcon />}>
            Sign out
          </ActionButton>
        </div>
      </Panel>
    </div>
  )
}
