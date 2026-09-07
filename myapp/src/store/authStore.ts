/**
 * Auth state for the whole app: who is signed in, the tokens that prove it, and
 * the outcome of the last sign-in or sign-up attempt.
 *
 * Zustand rather than context: the token has to be readable from outside React
 * (the API client needs it for every request) and a store gives that for free
 * through `getState()`. The provider wiring at the bottom of this file is the
 * whole integration — no component ever passes a token anywhere.
 *
 * Components should select one field at a time — `useAuthStore((s) => s.failure)`
 * — rather than selecting an object literal. Zustand v5 compares selector results
 * with Object.is, so a selector that builds a new object on every call re-renders
 * on every store change.
 */

import { create } from 'zustand'
import { ApiError, setAuthTokenProvider, setUnauthorizedHandler } from '@/lib/apiClient'
import type { AuthFailure, LoginFormValues, RegisterFormValues, User } from '@/models'
import { toLoginRequest, toRegisterRequest } from '@/models'
import { authService, classifyAuthError } from '@/services/authService'
import { clearStoredSession, readStoredSession, writeStoredSession } from '@/store/authStorage'

export interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null

  /**
   * Which storage the session lives in — false means sessionStorage, true means
   * localStorage. Kept in state because `refreshSession` has to write the rotated
   * token pair back to the same place the session already is, and by then the
   * checkbox that decided it is long gone.
   */
  remember: boolean

  /** True while a login or register request is in flight. Disables the submit button. */
  isSubmitting: boolean

  /**
   * True from module load until a session restored from storage has been checked
   * against the API, and false immediately when there was nothing to check.
   *
   * A token in storage proves someone signed in once, not that the session is
   * still good, so for a moment the app is optimistically signed in on evidence it
   * has not verified. Anything that would act irreversibly on that — redirecting a
   * user away from the sign-in screen, say — should wait for this to clear.
   */
  isBootstrapping: boolean

  /** Why the last attempt failed, or null. Carries a `kind` the UI can branch on. */
  failure: AuthFailure | null

  /**
   * A success message to show on the *next* screen — set by `register` and read
   * by the sign-in page, which is where the user lands afterwards. The reset
   * password flow uses the same field, via `setNotice`, to greet the user with
   * "your password has been reset" once they land back on sign-in.
   */
  notice: string | null

  /** Resolves true on success so the caller can navigate without watching state. */
  login: (values: LoginFormValues) => Promise<boolean>
  register: (values: RegisterFormValues) => Promise<boolean>
  logout: () => void

  /**
   * Trades the refresh token for a fresh pair. Registered with the API client, which
   * calls it on a 401 and replays the failed request if it resolves true — so no
   * screen ever calls this directly.
   */
  refreshSession: () => Promise<boolean>

  /** Validates a restored session on startup. Called once, from main.tsx. */
  bootstrap: () => Promise<void>

  clearFailure: () => void
  clearNotice: () => void

  /**
   * Sets the notice shown on the next screen the user lands on. Exists for
   * `ResetPasswordPage`, which is not itself part of the login/register flow
   * above but wants the same "here's what just happened" banner on sign-in
   * once the reset completes — reusing the field beats inventing a second one
   * that LoginPage would also have to know how to read.
   */
  setNotice: (message: string) => void
}

/**
 * Read once, at module load, so the first render already knows whether someone is
 * signed in. Doing this in an effect instead would flash the sign-in screen at
 * every returning user before redirecting them away from it.
 */
const restored = readStoredSession()

/**
 * Shown when a session ends by itself rather than by request.
 *
 * `expired` exists as its own kind because the alternative was reusing `invalid`,
 * which is styled as the user's mistake. Being signed out after seven days away is
 * nobody's mistake, and telling someone in red that their credentials were wrong
 * when they never typed any is just misleading. `classifyAuthError` never produces
 * this kind — it comes only from the two paths below, which know the difference
 * between a rejected password and a session that ran out.
 */
const SESSION_EXPIRED: AuthFailure = {
  kind: 'expired',
  message: 'Your session has ended. Sign in to pick up where you left off.',
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  user: restored?.session.user ?? null,
  accessToken: restored?.session.accessToken ?? null,
  refreshToken: restored?.session.refreshToken ?? null,
  remember: restored?.remember ?? false,
  isBootstrapping: restored !== null,
  isSubmitting: false,
  failure: null,
  notice: null,

  async login(values) {
    set({ isSubmitting: true, failure: null, notice: null })

    try {
      const response = await authService.login(toLoginRequest(values))

      writeStoredSession(
        {
          user: response.user,
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
        },
        values.remember,
      )

      set({
        user: response.user,
        accessToken: response.access_token,
        refreshToken: response.refresh_token,
        remember: values.remember,
        isSubmitting: false,
        failure: null,
      })

      return true
    } catch (error) {
      set({ isSubmitting: false, failure: classifyAuthError(error) })
      return false
    }
  },

  /**
   * Creates the account but does not sign the user in — the endpoint returns 201
   * with the new user and no tokens, so there is nothing to sign in with. The
   * notice set here is what the sign-in page shows when they arrive.
   *
   * `toRegisterRequest` decides what actually goes: everything except the account
   * type, which cannot be honoured because the public endpoint always creates a
   * standard user and promotion is an administrator's action.
   */
  async register(values) {
    set({ isSubmitting: true, failure: null, notice: null })

    try {
      const created = await authService.register(toRegisterRequest(values))

      set({
        isSubmitting: false,
        failure: null,
        notice: `Account created for ${created.email}. Sign in to continue.`,
      })

      return true
    } catch (error) {
      set({ isSubmitting: false, failure: classifyAuthError(error) })
      return false
    }
  },

  logout() {
    clearStoredSession()
    set({
      user: null,
      accessToken: null,
      refreshToken: null,
      remember: false,
      failure: null,
      notice: null,
    })
  },

  /**
   * Renews an expired access token without the user noticing.
   *
   * Registered with the API client at the bottom of this file, so it runs in
   * response to a 401 on any request rather than being called from a screen. It
   * sets no `failure` on the happy path — the whole point is that a routine token
   * expiry is invisible.
   *
   * The response's refresh token has to be persisted alongside the new access
   * token. Not because the old one stops working — the backend validates refresh
   * tokens by decoding them and keeps no record of which have been used, so the
   * original stays valid for its full seven days — but because reusing it means the
   * seven days never slide. A user active every single day would still be signed
   * out a week after they first signed in.
   */
  async refreshSession() {
    const { refreshToken, remember } = get()

    // Reachable when a request that was already in flight comes back 401 after a
    // sign-out has emptied the store. There is nothing to renew with, and calling
    // the endpoint with null would just be a 422.
    if (!refreshToken) {
      return false
    }

    try {
      const response = await authService.refresh(refreshToken)

      writeStoredSession(
        {
          user: response.user,
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
        },
        remember,
      )

      set({
        user: response.user,
        accessToken: response.access_token,
        refreshToken: response.refresh_token,
      })

      return true
    } catch (error) {
      /* A refresh that could not be *sent* says nothing about whether the session
         is still valid, so the tokens stay put and the original request simply
         fails. Clearing them here would sign people out over a dropped connection
         and throw away a refresh token that would have worked a moment later. */
      if (error instanceof ApiError && error.isOffline) {
        return false
      }

      // Anything else means the refresh token itself was rejected: seven days have
      // passed, or an administrator deactivated the account. The session is over.
      get().logout()
      set({ failure: SESSION_EXPIRED })

      return false
    }
  },

  /**
   * Confirms that a session restored from storage is still real.
   *
   * Storage can hold a token for a week after an admin disabled the account, or
   * after the refresh window closed. Without this check the app would render its
   * signed-in shell and only discover the truth when the first real request came
   * back 401 — which is a worse moment to find out, because by then the user is
   * looking at what they think is their own data.
   *
   * A 401 from `/me` has already been through one refresh attempt inside the API
   * client, so by the time it surfaces here `refreshSession` has tried and failed
   * and has already cleared the session.
   */
  async bootstrap() {
    if (!get().accessToken) {
      set({ isBootstrapping: false })
      return
    }

    // Who the restored session claimed to be, for the staleness check below.
    const expectedUserId = get().user?.id

    try {
      const user = await authService.me()

      const { user: current, accessToken, refreshToken, remember } = get()

      /* The session can change while /me is in flight: a sign-out, or a sign-in as
         somebody else from the form that RedirectIfAuthenticated deliberately shows
         during bootstrap. In either case this answer describes a session that is no
         longer the current one, and writing it back would pair one person's profile
         with another person's tokens.

         Compared by user id rather than by token, because a refresh in the middle of
         this legitimately rotates both tokens while the identity stays exactly the
         same — checking the token would throw away a perfectly good answer. */
      if (!accessToken || !refreshToken || current?.id !== expectedUserId) {
        set({ isBootstrapping: false })
        return
      }

      // The stored copy of the user may be days old. Overwriting it means a name
      // or company changed elsewhere shows up on this load rather than the next
      // full sign-in.
      writeStoredSession({ user, accessToken, refreshToken }, remember)
      set({ user, isBootstrapping: false })
    } catch (error) {
      if (error instanceof ApiError && error.isOffline) {
        /* The API is unreachable, which during development usually means it simply
           is not running yet. The session is kept: signing everyone out because a
           server restarted would be its own bug, and the next real request will
           fail honestly anyway. */
        set({ isBootstrapping: false })
        return
      }

      /* Same staleness check as the success path, and it matters more here. This
         failure is about the session bootstrap started with; if the user has since
         signed out deliberately, announcing that their session expired would be
         both untrue and confusing, and if they have signed in as someone else,
         acting on it would sign that person straight back out. */
      if (get().user?.id !== expectedUserId) {
        set({ isBootstrapping: false })
        return
      }

      /* Everything left is the session being over, and there is deliberately no
         special case for a disabled account. Both `/me` and `/refresh` answer a
         deactivated user with a plain 401 rather than a 403 — only the login route
         says "This account has been disabled" — so the honest sequence is this
         banner, and then the real reason when they try to sign in again. */
      get().logout()
      set({ isBootstrapping: false, failure: SESSION_EXPIRED })
    }
  },

  clearFailure() {
    set({ failure: null })
  },

  clearNotice() {
    set({ notice: null })
  },

  setNotice(message) {
    set({ notice: message })
  },
}))

/**
 * Hands the API client a way to read the current token.
 *
 * A getter, not the string: a refresh or a sign-out then takes effect on the very
 * next request instead of at the next full page load. This runs once, when the
 * module is first imported, and is the only place the two halves are connected.
 */
setAuthTokenProvider(() => useAuthStore.getState().accessToken)

/**
 * And a way to recover from a 401.
 *
 * Read through `getState()` rather than captured, for the same reason as above —
 * this file is evaluated while the store is still being created, so there is no
 * state to close over yet.
 *
 * The client guarantees only one of these runs at a time, so a burst of requests
 * that all expire together produces one refresh rather than one each.
 */
setUnauthorizedHandler(() => useAuthStore.getState().refreshSession())

/* -------------------------------------------------------------------------- */
/* Selectors                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Both halves are checked because either alone is meaningless: a token with no
 * user cannot be rendered, and a user with no token cannot make a request.
 */
export const selectIsAuthenticated = (state: AuthState): boolean =>
  state.accessToken !== null && state.user !== null

export const selectIsAdmin = (state: AuthState): boolean => state.user?.role === 'admin'
