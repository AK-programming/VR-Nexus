/**
 * Users — the admin-only page from the client review meeting: every account
 * in one table, and a per-account panel where an admin ticks which optional
 * sections (Documents, AI Assistant, Tender Analysis, Tender Tools) that
 * account can reach. A fresh USER account starts with none of them checked;
 * an ADMIN account has no checkboxes at all, because its access is already
 * everything, unconditionally, on both sides of the API — see
 * backend/app/api/deps.py's `require_feature` and this app's `RequireAdmin`.
 *
 * Reachable only via ROUTES.adminUsers, itself wrapped in RequireAdmin
 * (@/app/guards.tsx) — a non-admin never renders this page. That guard is
 * still only the client's half: GET /api/admin/users and PATCH
 * .../access are both behind `require_role(UserRole.ADMIN)` on the backend,
 * which is what actually stops a non-admin from reaching the data.
 *
 * Each checkbox click PATCHes immediately with the full replacement list —
 * matching the endpoint's own contract (see UpdateUserAccessRequest's
 * docstring) — rather than batching edits behind a Save button. One checkbox
 * is one grant or one revoke; there is no draft state to lose or to abandon.
 */

import { useMemo, useState } from 'react'
import { FEATURE_KEYS, FEATURE_LABELS } from '@/models'
import type { FeatureKey } from '@/models'
import type { AdminUser } from '@/models/admin'
import { adminService } from '@/services/adminService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { useAuthStore } from '@/store/authStore'
import { formatInitials, formatRelativeTime, formatRole, formatShortDate } from '@/lib/formatting'
import { errorMessage } from '@/lib/apiClient'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { DataTable, TableEmptyState, type Column } from '@/components/ui/DataTable'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { CheckIcon, RefreshIcon, ShieldCheckIcon, TrashIcon, UsersIcon } from '@/components/ui/icons'

/** Green "active" / neutral "disabled" — the same two-state pill idiom the rest of the product uses for a boolean status. */
function StatusPill({ active }: { active: boolean }) {
  return (
    <span
      className={[
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        active ? 'bg-emerald-50 text-emerald-700' : 'bg-neutral-100 text-neutral-600',
      ].join(' ')}
    >
      {active ? 'Active' : 'Disabled'}
    </span>
  )
}

function AccessSummary({ user }: { user: AdminUser }) {
  if (user.role === 'admin') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-brand-700">
        <ShieldCheckIcon className="size-3.5" />
        Full access
      </span>
    )
  }

  const count = user.feature_access.length

  if (count === 0) {
    return <span className="text-xs text-neutral-500">No access granted</span>
  }

  return (
    <span className="text-xs text-neutral-600">
      {count} of {FEATURE_KEYS.length} section{count === 1 ? '' : 's'}
    </span>
  )
}

export function AdminUsersPage() {
  const currentUserId = useAuthStore((state) => state.user?.id ?? null)
  const data = useAsyncData((signal) => adminService.listUsers(signal), [])
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  /** userId of the checkbox currently mid-PATCH, so only that row's boxes disable. */
  const [savingUserId, setSavingUserId] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  /* The account a "Delete user" click is confirming, or null when the dialog is
     closed. Holding the whole user rather than just an id gives the dialog's
     description a name to put in it without a second lookup. */
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function handleDeleteConfirmed() {
    if (!deleteTarget) {
      return
    }

    const target = deleteTarget
    setIsDeleting(true)
    setDeleteError(null)

    try {
      await adminService.deleteUser(target.id)
      setDeleteTarget(null)
      setSelectedUserId((current) => (current === target.id ? null : current))
      /* A fresh GET rather than filtering the row out locally - the merged-
         overrides pattern above exists for optimistic *edits*, and a removed
         row is simpler to just re-fetch than to teach that pattern to erase
         entries too. */
      await data.refetch()
    } catch (error) {
      setDeleteError(errorMessage(error))
    } finally {
      setIsDeleting(false)
    }
  }

  const users = data.data ?? []

  /**
   * `useAsyncData` owns `data.data` and exposes no setter for it — by design,
   * see its own file: a page is meant to re-fetch, not reach in and mutate
   * its cache. A toggle here needs to feel instant, not wait on a full GET,
   * so this keeps a small local patch set instead and merges it over
   * `data.data` at render time (`mergedUsers` below). A `refetch()` (the
   * Refresh button) clears the need for these the normal way: fresh data
   * from the server simply supersedes them.
   */
  const [overrides, setOverrides] = useState<Record<string, Partial<AdminUser>>>({})

  function patchUserInPlace(userId: string, patch: Partial<AdminUser>) {
    setOverrides((current) => ({ ...current, [userId]: { ...current[userId], ...patch } }))
  }

  /**
   * Applies one checkbox's new value to the user's list and PATCHes the
   * complete result. Optimistic: the row updates immediately, and is rolled
   * back only if the request actually fails — a checkbox that visibly
   * reverts a moment after being clicked is a worse experience than the rare
   * failed request, but a silent failure that leaves the box checked when
   * the grant never landed would be worse still.
   */
  async function toggleFeature(user: AdminUser, feature: FeatureKey, granted: boolean) {
    const nextFeatures = granted
      ? [...user.feature_access, feature]
      : user.feature_access.filter((key) => key !== feature)

    setSaveError(null)
    setSavingUserId(user.id)

    const previous = user.feature_access
    patchUserInPlace(user.id, { feature_access: nextFeatures })

    try {
      const updated = await adminService.updateUserAccess(user.id, { feature_access: nextFeatures })
      patchUserInPlace(user.id, updated)
    } catch (error) {
      patchUserInPlace(user.id, { feature_access: previous })
      setSaveError(errorMessage(error))
    } finally {
      setSavingUserId(null)
    }
  }

  const mergedUsers = useMemo(
    () => users.map((user) => ({ ...user, ...overrides[user.id] })),
    [users, overrides],
  )
  const mergedSelectedUser = useMemo(
    () => mergedUsers.find((user) => user.id === selectedUserId) ?? null,
    [mergedUsers, selectedUserId],
  )

  const columns: Column<AdminUser>[] = [
    {
      id: 'name',
      header: 'Name',
      sortValue: (row) => row.name,
      cell: (row) => (
        <button
          type="button"
          onClick={() => setSelectedUserId(row.id)}
          className={[
            'flex items-center gap-2.5 rounded-lg text-left transition-colors',
            'hover:text-brand-700 focus-visible:outline-brand-300',
            row.id === selectedUserId ? 'font-semibold text-brand-700' : 'text-neutral-800',
          ].join(' ')}
        >
          <span
            aria-hidden="true"
            className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 font-display text-[0.65rem] font-semibold text-brand-700"
          >
            {formatInitials(row.name)}
          </span>
          <span className="truncate">{row.name}</span>
        </button>
      ),
    },
    { id: 'email', header: 'Email', sortValue: (row) => row.email, cell: (row) => row.email, className: 'hidden sm:table-cell' },
    {
      id: 'role',
      header: 'Role',
      sortValue: (row) => row.role,
      cell: (row) => formatRole(row.role),
      className: 'hidden md:table-cell',
    },
    {
      id: 'status',
      header: 'Status',
      sortValue: (row) => (row.is_active ? 1 : 0),
      cell: (row) => <StatusPill active={row.is_active} />,
    },
    {
      id: 'access',
      header: 'Access',
      cell: (row) => <AccessSummary user={row} />,
      className: 'hidden lg:table-cell',
    },
    {
      id: 'created',
      header: 'Joined',
      sortValue: (row) => row.created_at,
      cell: (row) => formatShortDate(row.created_at),
      className: 'hidden xl:table-cell',
    },
    {
      id: 'last_login',
      header: 'Last active',
      sortValue: (row) => row.last_login_at,
      cell: (row) => (row.last_login_at ? formatRelativeTime(row.last_login_at) : 'Never'),
      className: 'hidden xl:table-cell',
    },
  ]

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            Users
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Every account in the workspace, and which sections each one can reach.
          </p>
        </div>
        <ActionButton
          variant="secondary"
          size="sm"
          leadingIcon={<RefreshIcon />}
          disabled={data.isRefreshing}
          onClick={data.refetch}
        >
          Refresh
        </ActionButton>
      </header>

      {/* Stacked, not side-by-side: the client asked for "All accounts" to stretch
          to the full width, with "Select a user" underneath it rather than squeezed
          into a narrow fixed-width rail beside it. */}
      <div className="flex flex-col gap-4">
        <Panel title="All accounts" description={`${mergedUsers.length} account${mergedUsers.length === 1 ? '' : 's'}`} flush>
          {data.status === 'error' && data.data === null ? (
            <ErrorBlock
              title="Users could not be loaded"
              message={data.error ?? 'The request did not complete.'}
              offline={data.offline}
              onRetry={data.refetch}
            />
          ) : data.status === 'loading' && data.data === null ? (
            <LoadingRows rows={6} label="Loading users" />
          ) : mergedUsers.length === 0 ? (
            <div className="py-10">
              <TableEmptyState
                icon={<UsersIcon className="size-5" />}
                title="No accounts yet"
                description="Accounts appear here as soon as someone registers."
              />
            </div>
          ) : (
            <DataTable
              rows={mergedUsers}
              columns={columns}
              rowKey={(row) => row.id}
              caption="Every account and its granted sections"
              initialSort={{ columnId: 'name', direction: 'asc' }}
            />
          )}
        </Panel>

        <Panel
          title={mergedSelectedUser ? mergedSelectedUser.name : 'Select a user'}
          description={
            mergedSelectedUser
              ? mergedSelectedUser.email
              : 'Click a name in the table to edit their access.'
          }
          action={
            /* Same two rules the backend enforces (see delete_user's docstring):
               no deleting your own signed-in account, and no deleting an ADMIN
               row here. Both are hidden rather than shown-and-disabled, since
               there is nothing the admin can do on this page to unblock either
               one. */
            mergedSelectedUser &&
            mergedSelectedUser.id !== currentUserId &&
            mergedSelectedUser.role !== 'admin' ? (
              <ActionButton
                variant="danger"
                size="sm"
                leadingIcon={<TrashIcon />}
                onClick={() => {
                  setDeleteError(null)
                  setDeleteTarget(mergedSelectedUser)
                }}
              >
                Delete user
              </ActionButton>
            ) : null
          }
        >
          {deleteError ? (
            <p className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
              {deleteError}
            </p>
          ) : null}
          {!mergedSelectedUser ? (
            <p className="text-sm text-neutral-500">
              Nothing has access to a section by default. Pick an account, then tick each
              feature they should be able to open.
            </p>
          ) : mergedSelectedUser.role === 'admin' ? (
            <div className="flex flex-col items-start gap-2 text-sm text-neutral-600">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700">
                <ShieldCheckIcon className="size-3.5" />
                Full access
              </span>
              <p>
                Admin accounts already have unconditional access to every section, so there is
                nothing to grant here.
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-1">
              {saveError ? (
                <p className="mb-2 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{saveError}</p>
              ) : null}
              {FEATURE_KEYS.map((feature) => {
                const checked = mergedSelectedUser.feature_access.includes(feature)
                const disabled = savingUserId === mergedSelectedUser.id

                return (
                  <label
                    key={feature}
                    className={[
                      'flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors',
                      disabled ? 'opacity-60' : 'hover:bg-surface-muted',
                    ].join(' ')}
                  >
                    <span className="relative inline-flex">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={(event) =>
                          toggleFeature(mergedSelectedUser, feature, event.target.checked)
                        }
                        className="peer absolute inset-0 size-full cursor-pointer appearance-none rounded-md disabled:cursor-not-allowed"
                      />
                      <span
                        aria-hidden="true"
                        className={[
                          'flex size-5 items-center justify-center rounded-md border transition-all duration-150',
                          'text-transparent',
                          'peer-checked:border-brand-500 peer-checked:bg-brand-500 peer-checked:text-white',
                          'peer-focus-visible:ring-4 peer-focus-visible:ring-brand-500/25',
                          checked ? '' : 'border-neutral-300 bg-surface peer-hover:border-brand-400',
                        ].join(' ')}
                      >
                        <CheckIcon className="size-3.5" />
                      </span>
                    </span>
                    <span className="text-sm font-medium text-neutral-800">
                      {FEATURE_LABELS[feature]}
                    </span>
                  </label>
                )
              })}
            </div>
          )}
        </Panel>
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this account?"
        description={
          deleteTarget
            ? `${deleteTarget.name} (${deleteTarget.email}) will lose access immediately and be removed from this list. This cannot be undone.`
            : ''
        }
        confirmLabel={isDeleting ? 'Deleting…' : 'Delete user'}
        onConfirm={() => {
          if (!isDeleting) {
            void handleDeleteConfirmed()
          }
        }}
        onCancel={() => {
          if (!isDeleting) {
            setDeleteTarget(null)
          }
        }}
      />
    </div>
  )
}
