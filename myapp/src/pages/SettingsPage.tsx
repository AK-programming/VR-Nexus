/**
 * Settings — workspace and appearance preferences.
 *
 * Real controls only: the theme selector genuinely switches the app between light,
 * dark and follow-system (persisted per browser); the account block reflects the
 * signed-in user and offers the one exit. Nothing here is a switch that does
 * nothing — a settings page full of inert toggles is worse than a short honest one,
 * and the rest (notification channels, workspace defaults) arrives when it has a
 * backend to talk to.
 */

import { ROUTES } from '@/constants/routes'
import { formatRole } from '@/lib/formatting'
import { useAuthStore } from '@/store/authStore'
import { useThemeStore } from '@/store/themeStore'
import type { Theme } from '@/lib/theme'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { LogOutIcon, UserCircleIcon } from '@/components/ui/icons'

const THEME_OPTIONS: { value: Theme; label: string; hint: string }[] = [
  { value: 'light', label: 'Light', hint: 'Always the light palette' },
  { value: 'dark', label: 'Dark', hint: 'Always the dark palette' },
  { value: 'system', label: 'System', hint: 'Follow your device setting' },
]

export function SettingsPage() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const theme = useThemeStore((state) => state.theme)
  const setTheme = useThemeStore((state) => state.setTheme)

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
          Settings
        </h1>
        <p className="mt-1 text-sm text-neutral-500">
          Workspace, appearance and account preferences.
        </p>
      </header>

      {/* Appearance */}
      <Panel collapsible defaultOpen title="Appearance" description="How VR-Nexus looks on this device.">
        <fieldset>
          <legend className="text-sm font-medium text-neutral-800">Theme</legend>
          <p className="mt-1 text-xs text-neutral-500">
            Saved in this browser. The branded navigation stays dark in every theme.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
            {THEME_OPTIONS.map((option) => {
              const active = theme === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setTheme(option.value)}
                  aria-pressed={active}
                  className={[
                    'flex flex-col items-start rounded-xl border px-3.5 py-3 text-left transition-colors duration-150',
                    active
                      ? 'border-brand-400 bg-selected ring-1 ring-brand-200'
                      : 'border-hairline bg-surface hover:border-neutral-300 hover:bg-surface-muted',
                  ].join(' ')}
                >
                  <span className="text-sm font-semibold text-neutral-900">{option.label}</span>
                  <span className="mt-0.5 text-xs text-neutral-500">{option.hint}</span>
                </button>
              )
            })}
          </div>
        </fieldset>
      </Panel>

      {/* Account */}
      <Panel collapsible defaultOpen title="Account" description="Your identity in this workspace.">
        <dl className="flex flex-col divide-y divide-hairline">
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Name</dt>
            <dd className="text-sm font-medium text-neutral-900">{user?.name ?? '-'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Email</dt>
            <dd className="truncate text-sm font-medium text-neutral-900">{user?.email ?? '-'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Role</dt>
            <dd className="text-sm font-medium text-neutral-900">{formatRole(user?.role) || '-'}</dd>
          </div>
        </dl>

        <div className="mt-4 flex flex-wrap gap-2">
          <ActionButton variant="secondary" size="sm" to={ROUTES.profile} leadingIcon={<UserCircleIcon />}>
            Edit profile
          </ActionButton>
          <ActionButton variant="danger" size="sm" onClick={logout} leadingIcon={<LogOutIcon />}>
            Sign out
          </ActionButton>
        </div>
      </Panel>

      {/* About */}
      <Panel collapsible defaultOpen title="About" description="Build information.">
        <dl className="flex flex-col divide-y divide-hairline">
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Product</dt>
            <dd className="text-sm font-medium text-neutral-900">VR-Nexus - Tender Intelligence</dd>
          </div>
          <div className="flex items-center justify-between gap-4 py-2.5">
            <dt className="text-sm text-neutral-500">Version</dt>
            <dd className="text-sm font-medium text-neutral-900 tabular-nums">1.0.0</dd>
          </div>
        </dl>
      </Panel>
    </div>
  )
}
