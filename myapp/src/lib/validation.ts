/**
 * Field-level validation for the auth forms.
 *
 * These checks exist to save a round trip and to put the message next to the
 * field that caused it — not to be the authority on what is valid. The server
 * validates everything again, and where the two disagree the server wins.
 *
 * Each function returns the message to show, or undefined when the value passes,
 * so a form can build its error map with a plain object literal.
 */

import {
  NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  PHONE_MAX_LENGTH,
} from '@/models'

/**
 * Deliberately loose: something, an @, something, a dot, something. A stricter
 * pattern would reject valid but unusual addresses, and the only check that
 * actually matters is the server's EmailStr. This one catches the typo where
 * someone hasn't finished typing.
 */
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateName(value: string): string | undefined {
  const name = value.trim()

  if (!name) {
    return 'Enter your full name.'
  }
  if (name.length > NAME_MAX_LENGTH) {
    return `Keep this under ${NAME_MAX_LENGTH} characters.`
  }
  return undefined
}

export function validateEmail(value: string): string | undefined {
  const email = value.trim()

  if (!email) {
    return 'Enter your email address.'
  }
  if (!EMAIL_PATTERN.test(email)) {
    return 'Enter a valid email address, like name@company.com.'
  }
  return undefined
}

/**
 * For a new password only. Sign-in uses `validatePasswordPresent` instead —
 * holding an existing password to today's rules would lock out anyone whose
 * account predates them, and the length of a stored password is not the sign-in
 * screen's business.
 *
 * The upper bound is measured in bytes, not characters, because bcrypt's 72-byte
 * ceiling is a byte ceiling and passlib raises rather than truncating quietly. A
 * 72-character password of accented or non-Latin characters passes both
 * `value.length` and the server's Pydantic check, then fails inside the hash call
 * as a 500 — so it has to be caught here, next to the field, where it can still be
 * explained.
 */
export function validateNewPassword(value: string): string | undefined {
  if (!value) {
    return 'Choose a password.'
  }
  if (value.length < PASSWORD_MIN_LENGTH) {
    return `Use at least ${PASSWORD_MIN_LENGTH} characters.`
  }

  const bytes = new TextEncoder().encode(value).length

  if (bytes > PASSWORD_MAX_LENGTH) {
    /* For an all-ASCII password the two counts agree, and "characters" is what
       people expect to hear. Only mention the difference when there is one. */
    return bytes === value.length
      ? `Use ${PASSWORD_MAX_LENGTH} characters or fewer.`
      : 'This password is too long. Accented and non-Latin characters take up more than one place, so shorten it by a few.'
  }

  return undefined
}

export function validatePasswordPresent(value: string): string | undefined {
  return value ? undefined : 'Enter your password.'
}

export function validateConfirmPassword(
  password: string,
  confirmation: string,
): string | undefined {
  if (!confirmation) {
    return 'Re-enter your password.'
  }
  if (password !== confirmation) {
    return 'Both passwords must match.'
  }
  return undefined
}

/**
 * Optional field, so an empty value passes. Digits, spaces, dashes, brackets and
 * a leading + cover every format people actually type; anything else is a typo.
 *
 * The upper bound comes from the constant rather than the pattern so it stays tied
 * to the server's `max_length=32`. Hard-coding a smaller number in the regex would
 * make the client reject numbers the API would have accepted.
 */
export function validateOptionalPhone(value: string): string | undefined {
  const phone = value.trim()

  if (!phone) {
    return undefined
  }
  if (phone.length > PHONE_MAX_LENGTH) {
    return `Keep this under ${PHONE_MAX_LENGTH} characters.`
  }
  if (!/^\+?[\d\s()-]{7,}$/.test(phone)) {
    return 'Enter a valid phone number, or leave this blank.'
  }
  return undefined
}

/**
 * How strong a new password looks, for the meter under the password field.
 *
 * This is feedback, not a gate — the only rule that blocks submission is the
 * length check above. Score runs 0-4 so it maps directly onto the four segments
 * the meter draws.
 */
export interface PasswordStrength {
  score: 0 | 1 | 2 | 3 | 4
  label: string
}

export function measurePasswordStrength(value: string): PasswordStrength {
  if (!value) {
    return { score: 0, label: 'Empty' }
  }

  let score = 0

  if (value.length >= PASSWORD_MIN_LENGTH) score += 1
  if (value.length >= 12) score += 1
  if (/[a-z]/.test(value) && /[A-Z]/.test(value)) score += 1
  if (/\d/.test(value) && /[^\w\s]/.test(value)) score += 1

  const labels = ['Too short', 'Weak', 'Fair', 'Strong', 'Very strong'] as const
  const clamped = Math.min(score, 4) as PasswordStrength['score']

  return { score: clamped, label: labels[clamped] }
}
