/**
 * Where a signed-in session lives between page loads.
 *
 * This is hand-rolled rather than done with zustand's `persist` middleware for
 * one reason: "Remember me" has to choose the storage. A session the user asked
 * to be remembered belongs in localStorage; one they did not belongs in
 * sessionStorage, so closing the tab ends it. `persist` resolves its storage once
 * at module load, which cannot express a choice made later at sign-in.
 *
 * Every access is wrapped, because reading storage is not guaranteed to succeed —
 * Safari's private mode and hardened browser settings both throw on access rather
 * than returning null. A browser that refuses to store anything should mean "you
 * are signed out on next load", never a blank screen.
 */

import type { User } from '@/models'
import { isUserRole } from '@/models'

const STORAGE_KEY = 'vr-nexus.auth'

export interface StoredSession {
  user: User
  accessToken: string
  refreshToken: string
}

/**
 * A session read back from storage, plus where it was found.
 *
 * `remember` is derived from which store held it rather than saved alongside it.
 * Persisting the flag as well would mean two sources of truth for one fact, free
 * to disagree — and the storage location already *is* the answer.
 */
export interface RestoredSession {
  session: StoredSession
  remember: boolean
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Storage is user-writable and survives deploys, so anything read back out of it
 * is untrusted input. A session written by an older build with a different shape
 * must be discarded, not partially believed — the alternative is a crash deep in
 * a component that assumed `user.name` was a string.
 *
 * Only the fields something would crash on are checked. `phone_number` and
 * `company` are nullable display values, so a session saved before they existed
 * stays usable and simply renders them as missing.
 */
function isStoredSession(value: unknown): value is StoredSession {
  if (!isRecord(value)) return false

  const { user, accessToken, refreshToken } = value

  if (typeof accessToken !== 'string' || !accessToken) return false
  if (typeof refreshToken !== 'string' || !refreshToken) return false
  if (!isRecord(user)) return false

  return (
    typeof user.id === 'string' &&
    typeof user.name === 'string' &&
    typeof user.email === 'string' &&
    typeof user.is_active === 'boolean' &&
    // Lowercased before the check so a session saved by a build that stored the
    // enum name survives instead of being thrown away as unrecognised.
    typeof user.role === 'string' &&
    isUserRole(user.role.toLowerCase())
  )
}

/**
 * The picker is a function so that touching `window.sessionStorage` happens inside
 * the try. In hardened and private-mode browsers the property access itself throws,
 * before any method is even called.
 */
function readFrom(pick: () => Storage): StoredSession | null {
  let raw: string | null = null

  try {
    raw = pick().getItem(STORAGE_KEY)
  } catch {
    return null
  }

  if (!raw) return null

  try {
    const parsed: unknown = JSON.parse(raw)
    return isStoredSession(parsed) ? parsed : null
  } catch {
    return null
  }
}

/**
 * Both stores are searched, because which one holds the session depends on the
 * "Remember me" choice made at sign-in. sessionStorage is checked first: if both
 * somehow hold a session, the tab-scoped one represents the more recent decision.
 */
export function readStoredSession(): RestoredSession | null {
  const tabScoped = readFrom(() => window.sessionStorage)
  if (tabScoped) {
    return { session: tabScoped, remember: false }
  }

  const persistent = readFrom(() => window.localStorage)
  if (persistent) {
    return { session: persistent, remember: true }
  }

  return null
}

/**
 * Writes to one store and clears the other, so a user who signs in once with
 * "Remember me" and again without it does not leave a stale copy behind in
 * localStorage that would outlive the tab they expected it to die with.
 */
export function writeStoredSession(session: StoredSession, remember: boolean): void {
  const raw = JSON.stringify(session)

  try {
    if (remember) {
      window.localStorage.setItem(STORAGE_KEY, raw)
      window.sessionStorage.removeItem(STORAGE_KEY)
    } else {
      window.sessionStorage.setItem(STORAGE_KEY, raw)
      window.localStorage.removeItem(STORAGE_KEY)
    }
  } catch {
    // Storage is full or blocked. The in-memory session still works for this
    // page load; it just will not survive a refresh.
  }
}

export function clearStoredSession(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY)
    window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing to do — if it cannot be removed it could not have been written.
  }
}
