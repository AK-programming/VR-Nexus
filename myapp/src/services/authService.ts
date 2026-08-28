/**
 * The auth endpoints, and the one place that knows what their status codes mean.
 *
 * Requests go through `api` in @/lib/apiClient, so this file has no fetch, no
 * base URL and no error-shape parsing of its own. What it adds is the translation
 * from HTTP to domain: a 423 is not "an error", it is a locked account with a
 * countdown, and the screens should be able to say so without inspecting
 * response codes themselves.
 *
 * Backend reference: backend/app/api/routes/auth.py — the single merged backend.
 * VR-Nexus-maryam and VR_Project are archival and are no longer run.
 */

import { ApiError, api, errorMessage } from '@/lib/apiClient'
import { normalizeUser } from '@/models'
import type {
  AuthFailure,
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  User,
} from '@/models'

/**
 * Paths, not full URLs. They stay relative so development traffic passes through
 * the Vite proxy defined in vite.config.ts, and every request the browser makes is
 * same-origin.
 *
 * The merged backend does register CORS middleware, with Vite's 5173 in its
 * allowed origins, so a direct cross-origin call would now succeed. Keep the
 * relative paths anyway: going direct means every request depends on the server's
 * CORS_ORIGINS list matching wherever the app happens to be served from, and it
 * puts preflights on the critical path of a cross-origin POST. Same-origin needs
 * neither. Leave VITE_API_BASE_URL empty and this file needs no changes.
 *
 * The prefix comes from the router itself: APIRouter(prefix="/api/auth").
 */
export const AUTH_ENDPOINTS = {
  login: '/api/auth/login',
  register: '/api/auth/register',
  refresh: '/api/auth/refresh',
  me: '/api/auth/me',
} as const

/**
 * Every method that returns a user passes it through `normalizeUser` first, so the
 * role casing is repaired at the single point where server data enters the app.
 * Doing it here rather than in the store means storage, selectors and components
 * all see one canonical shape and none of them has to know the wire is ambiguous.
 */
export const authService = {
  /**
   * Exchanges credentials for a token pair.
   *
   * `anonymous` because a token left over from a previous session has no place on
   * a sign-in request — the endpoint ignores it, and sending it would mean a
   * stale credential travels with an unauthenticated call. It also keeps the
   * client's 401 retry away from this call: a 401 here is a wrong password, and
   * refreshing in response to one would make no sense.
   */
  async login(payload: LoginRequest, signal?: AbortSignal): Promise<TokenResponse> {
    const response = await api.postJson<TokenResponse>(AUTH_ENDPOINTS.login, payload, {
      signal,
      anonymous: true,
    })

    return { ...response, user: normalizeUser(response.user) }
  },

  /**
   * Creates an account and returns the new user — deliberately not a token pair.
   *
   * The endpoint responds 201 with `UserOut`, so a successful registration does
   * not sign anyone in. That is the server's design, and the UI honours it by
   * sending the user to sign-in rather than faking a session.
   */
  async register(payload: RegisterRequest, signal?: AbortSignal): Promise<User> {
    const created = await api.postJson<User>(AUTH_ENDPOINTS.register, payload, {
      signal,
      anonymous: true,
    })

    return normalizeUser(created)
  },

  /**
   * Trades a refresh token for a fresh pair. The refresh token travels in the
   * body, so this call needs no Authorization header of its own.
   *
   * The server issues a new refresh token as well as a new access token, and the
   * caller should store both. The old one does keep working — refresh tokens are
   * validated by decoding, with no record kept of which have been exchanged — but
   * holding onto it pins the session's expiry to seven days after sign-in instead
   * of letting the window slide forward with use.
   */
  async refresh(refreshToken: string, signal?: AbortSignal): Promise<TokenResponse> {
    const response = await api.postJson<TokenResponse>(
      AUTH_ENDPOINTS.refresh,
      { refresh_token: refreshToken },
      { signal, anonymous: true },
    )

    return { ...response, user: normalizeUser(response.user) }
  },

  /**
   * The current user, according to the access token. Used on boot to confirm a
   * restored session is still good — a token in localStorage proves only that
   * someone signed in once, not that the account is still active or that the
   * token has not expired since.
   */
  async me(signal?: AbortSignal): Promise<User> {
    return normalizeUser(await api.get<User>(AUTH_ENDPOINTS.me, { signal }))
  },
}

/**
 * Turns whatever was thrown into a reason the UI can branch on.
 *
 * The messages the server sends are already written for a person — including the
 * lockout countdown, which only the server can know — so they are passed through
 * rather than replaced. The fallbacks here only cover the cases where there is no
 * server message to show, which in practice means the request never arrived.
 *
 * 401 stays vague on purpose. The backend returns the same "Incorrect email or
 * password" for an unknown address as for a wrong password, so that the sign-in
 * screen cannot be used to find out which addresses have accounts. Splitting
 * that message in the client would give away exactly what the server withheld.
 */
export function classifyAuthError(error: unknown): AuthFailure {
  if (error instanceof ApiError) {
    if (error.isOffline) {
      return {
        kind: 'offline',
        message: 'Could not reach the server. Check your connection and try again.',
      }
    }

    switch (error.status) {
      case 401:
        return { kind: 'invalid', message: error.message }
      case 403:
        return { kind: 'disabled', message: error.message }
      case 409:
        return { kind: 'conflict', message: error.message }
      case 422:
        return { kind: 'validation', message: error.message }
      case 423:
        return { kind: 'locked', message: error.message }
      default:
        return { kind: 'unknown', message: error.message }
    }
  }

  return { kind: 'unknown', message: errorMessage(error) }
}
