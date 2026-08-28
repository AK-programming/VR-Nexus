/**
 * The auth wire contract, mirrored from the FastAPI service.
 *
 * Every type here has a counterpart in the backend's Pydantic models — see
 * backend/app/schemas/auth.py, in the single merged backend. Field names are snake_case
 * because that is what crosses the wire; renaming them in the client would mean
 * a mapping layer for no benefit, and would hide drift when the API changes.
 *
 * Keep this file free of React and free of fetch. It describes shapes only, so
 * services, the store and the forms can all agree on one definition.
 */

/* -------------------------------------------------------------------------- */
/* Roles                                                                      */
/* -------------------------------------------------------------------------- */

/**
 * Matches backend `UserRole(str, enum.Enum)`.
 *
 * Written as an `as const` array rather than a TS enum because tsconfig sets
 * erasableSyntaxOnly: enums emit runtime code and so cannot be stripped by
 * Vite's transpiler. The array doubles as the source for the union type below
 * and as something the UI can iterate over.
 */
export const USER_ROLES = ['admin', 'user'] as const

export type UserRole = (typeof USER_ROLES)[number]

/* -------------------------------------------------------------------------- */
/* Field limits                                                               */
/* -------------------------------------------------------------------------- */

/**
 * The server's own validation bounds, restated so the form can reject a value
 * before spending a round trip on it. These are not arbitrary UI choices — each
 * one matches a Field(...) constraint in the backend schema, and the client must
 * never be the more permissive of the two.
 */
export const NAME_MAX_LENGTH = 255

export const PASSWORD_MIN_LENGTH = 8

/**
 * 72, not a rounder number: bcrypt truncates its input at 72 bytes, so the
 * backend refuses anything longer rather than silently ignoring the tail of a
 * password the user believed was accepted.
 *
 * Note the unit. This is a limit on *bytes*, so `validateNewPassword` encodes the
 * string before comparing — `value.length` would let a 72-character accented
 * password through to a failure inside the hash call.
 */
export const PASSWORD_MAX_LENGTH = 72

/** Backend `phone_number: Optional[str] = Field(default=None, max_length=32)`. */
export const PHONE_MAX_LENGTH = 32

/** Backend `company: Optional[str] = Field(default=None, max_length=255)`. */
export const COMPANY_MAX_LENGTH = 255

/* -------------------------------------------------------------------------- */
/* Role coercion                                                              */
/* -------------------------------------------------------------------------- */

export function isUserRole(value: unknown): value is UserRole {
  return typeof value === 'string' && (USER_ROLES as readonly string[]).includes(value)
}

/**
 * Forces whatever arrived in a `role` field to a role this app knows.
 *
 * The wire value is lowercase — Pydantic serialises an enum by its `.value`, and
 * the backend's are `"admin"` and `"user"`. But the API handoff document describes
 * the field as `"USER"`, which is the enum's *name*, so there is real ambiguity
 * about what a future build might send. Getting this wrong fails quietly and
 * badly: an unrecognised role would make the stored-session guard reject a
 * perfectly good session on every reload, and the user would appear to be signed
 * out at random.
 *
 * Anything unrecognised becomes `user`, never `admin`. If this function ever has
 * to guess, it must guess at the least privilege.
 */
export function normalizeUserRole(value: unknown): UserRole {
  if (typeof value === 'string') {
    const lowered = value.toLowerCase()
    if (isUserRole(lowered)) {
      return lowered
    }
  }

  return 'user'
}

/**
 * Repairs a user as it arrives from the API. Typed as taking a `User` because
 * that is what the endpoint claims to return — the whole point is that the claim
 * is not fully trustworthy. Returns the original object untouched when there is
 * nothing to fix, so it does not invalidate referential equality for free.
 */
export function normalizeUser(user: User): User {
  const role = normalizeUserRole(user.role)
  return role === user.role ? user : { ...user, role }
}

/* -------------------------------------------------------------------------- */
/* Requests                                                                   */
/* -------------------------------------------------------------------------- */

/** POST /api/auth/login */
export interface LoginRequest {
  email: string
  password: string
}

/**
 * POST /api/auth/register
 *
 * There is deliberately no `role` here, and adding one would be a security bug
 * rather than a feature: the public endpoint ignores it, and if it did not,
 * anyone who can reach the API could hand themselves admin. New accounts are
 * always created as `user` and promoted by an existing administrator.
 *
 * `phone_number` and `company` are both nullable on the server and are written
 * straight to the user row, so an absent value is sent as null rather than "".
 */
export interface RegisterRequest {
  name: string
  email: string
  password: string
  phone_number: string | null
  company: string | null
}

/** POST /api/auth/refresh */
export interface RefreshRequest {
  refresh_token: string
}

/* -------------------------------------------------------------------------- */
/* Responses                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * Backend `UserOut`. `id` is a UUID and `last_login_at` an ISO-8601 timestamp —
 * both arrive as strings over JSON, so they are typed as strings here and parsed
 * at the point of use rather than guessed at on arrival.
 */
export interface User {
  id: string
  name: string
  email: string
  phone_number: string | null
  company: string | null
  role: UserRole
  is_active: boolean
  last_login_at: string | null
}

/** Backend `TokenResponse`. Returned by login and refresh — but not register. */
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

/* -------------------------------------------------------------------------- */
/* Form models                                                                */
/* -------------------------------------------------------------------------- */

/**
 * What the login form holds. `remember` never leaves the browser: the session is
 * persisted either way, and this only decides whether it outlives the tab.
 */
export interface LoginFormValues {
  email: string
  password: string
  remember: boolean
}

/**
 * What the registration form holds, which is still slightly more than the API
 * accepts.
 *
 * `phone` and `company` are now real — the endpoint takes both and writes them to
 * the user row. `role` is the one field that cannot be honoured: the public
 * endpoint has no `role` at all, so the form explains that admin is granted by an
 * existing administrator rather than pretending to request it. See
 * `toRegisterRequest` for exactly what leaves the browser.
 */
export interface RegisterFormValues {
  role: UserRole
  name: string
  email: string
  phone: string
  company: string
  password: string
  confirmPassword: string
  acceptedTerms: boolean
}

/**
 * Builds the request body, trimming the fields a user is likely to paste with
 * stray whitespace. The password is never trimmed — leading or trailing spaces
 * are legitimate characters in a password and stripping them would lock people
 * out of accounts they created correctly.
 *
 * `role`, `confirmPassword` and `acceptedTerms` stay in the browser: the first
 * because the server decides it, the other two because they are checks on the
 * form rather than data about the user.
 */
export function toRegisterRequest(values: RegisterFormValues): RegisterRequest {
  return {
    name: values.name.trim(),
    email: values.email.trim(),
    password: values.password,
    phone_number: blankToNull(values.phone),
    company: blankToNull(values.company),
  }
}

/**
 * An untouched optional field and an explicit "none" mean the same thing to this
 * API, and both columns are nullable, so a blank input is sent as null. Posting
 * "" instead would store an empty string that reads as present everywhere
 * downstream — `user.company` would be truthy and render as nothing.
 */
function blankToNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** Same narrowing for the login form. */
export function toLoginRequest(values: LoginFormValues): LoginRequest {
  return {
    email: values.email.trim(),
    password: values.password,
  }
}

/* -------------------------------------------------------------------------- */
/* Session                                                                    */
/* -------------------------------------------------------------------------- */

/** The part of a successful login the app keeps hold of. */
export interface AuthSession {
  user: User
  accessToken: string
  refreshToken: string
}

/**
 * Why an auth attempt failed, classified once so the UI can react to the reason
 * instead of pattern-matching on message text.
 *
 * The backend distinguishes these deliberately: `invalid` is returned for both
 * an unknown email and a wrong password, so the screen cannot be used to
 * discover which addresses have accounts. `locked` carries a countdown in its
 * message and is not the user's mistake, so it is worth a calmer tone than a
 * plain rejection.
 *
 * `expired` is the one kind that does not come from `classifyAuthError`, because
 * it does not correspond to a status code. The store raises it when a session ends
 * on its own — a refresh token past its seven days — and it is separate from
 * `invalid` because that is presented as the user's mistake, and this is not one.
 */
export type AuthErrorKind =
  | 'invalid' /* 401 — wrong email or password */
  | 'expired' /* the stored session ran out; nothing was typed wrong */
  | 'locked' /* 423 — too many failed attempts */
  | 'disabled' /* 403 — account switched off by an admin */
  | 'conflict' /* 409 — email already registered */
  | 'validation' /* 422 — the server rejected a field */
  | 'offline' /* the request never reached the server */
  | 'unknown'

export interface AuthFailure {
  kind: AuthErrorKind
  message: string
}
