/**
 * Reset password.
 *
 * Reached only from the link in a password reset email — `?token=` is the
 * opaque, signed value that link carries, and this screen never inspects it
 * beyond handing it back to the server unchanged. Only the server that signed
 * it can tell whether it is still genuine and still inside its 30-minute
 * window; a token that fails either check comes back as the same "invalid or
 * expired" message, because there is nothing more specific this screen could
 * say that would actually be true.
 *
 * A missing token — someone landing here by editing the URL rather than
 * following the email — gets a different screen entirely rather than a form
 * that would only fail once submitted.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/TextField'
import { AlertTriangleIcon, ArrowRightIcon, LockIcon } from '@/components/ui/icons'
import { ROUTES } from '@/constants/routes'
import { AuthLayout } from '@/Layout/AuthLayout'
import { errorMessage } from '@/lib/apiClient'
import type { PasswordStrength } from '@/lib/validation'
import {
  measurePasswordStrength,
  validateConfirmPassword,
  validateNewPassword,
} from '@/lib/validation'
import { PASSWORD_MAX_LENGTH } from '@/models'
import { authService } from '@/services/authService'
import { useAuthStore } from '@/store/authStore'

/* -------------------------------------------------------------------------- */
/* Password strength                                                          */
/* -------------------------------------------------------------------------- */

/**
 * Same meter as RegisterPage's. Not shared as a component because each is a
 * dozen lines wired to a local `STRENGTH_FILL` map — extracting it would trade
 * two small, obvious copies for one import plus a props contract, for a widget
 * neither screen is likely to change independently of the other by much.
 */
const STRENGTH_FILL: Record<PasswordStrength['score'], string> = {
  0: 'bg-brand-500',
  1: 'bg-brand-500',
  2: 'bg-amber-500',
  3: 'bg-lime-500',
  4: 'bg-emerald-500',
}

function StrengthMeter({ value }: { value: string }) {
  if (!value) {
    return null
  }

  const { score, label } = measurePasswordStrength(value)

  return (
    <div className="mt-2">
      <div className="flex gap-1.5" aria-hidden="true">
        {[1, 2, 3, 4].map((segment) => (
          <span
            key={segment}
            className={[
              'h-[3px] flex-1 rounded-full transition-colors',
              segment <= score ? STRENGTH_FILL[score] : 'bg-neutral-200',
            ].join(' ')}
          />
        ))}
      </div>
      <p className="mt-1.5 text-xs text-neutral-500">
        Strength: <span className="font-medium text-neutral-700">{label}</span>
      </p>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

type FieldErrors = {
  password?: string
  confirmPassword?: string
}

export function ResetPasswordPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [isSubmitting, setSubmitting] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)

  function changePassword(value: string) {
    setPassword(value)
    setErrors((current) => ({ ...current, password: undefined }))
    if (requestError) {
      setRequestError(null)
    }
  }

  function changeConfirmPassword(value: string) {
    setConfirmPassword(value)
    setErrors((current) => ({ ...current, confirmPassword: undefined }))
    if (requestError) {
      setRequestError(null)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!token) {
      return
    }

    const nextErrors: FieldErrors = {
      password: validateNewPassword(password),
      confirmPassword: validateConfirmPassword(password, confirmPassword),
    }
    setErrors(nextErrors)

    if (nextErrors.password || nextErrors.confirmPassword) {
      return
    }

    setSubmitting(true)
    setRequestError(null)

    try {
      const response = await authService.resetPassword({ token, new_password: password })
      /* Reuses the same "notice" banner LoginPage already shows after a fresh
         registration — one field, read by the one screen the user lands on
         next, rather than a second success channel LoginPage would also have
         to know about. */
      useAuthStore.getState().setNotice(response.message)
      navigate(ROUTES.login, { replace: true })
    } catch (error) {
      setRequestError(errorMessage(error))
      setSubmitting(false)
    }
  }

  if (!token) {
    return (
      <AuthLayout badge={<LockIcon />}>
        <header>
          <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
            Account recovery
          </p>
          <h1 className="mt-3 font-display text-[length:clamp(1.65rem,3.4dvh,2.3rem)] leading-[1.12] font-semibold tracking-tight text-neutral-900">
            Reset Link <span className="text-brand-500">Missing</span>
          </h1>
        </header>

        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AlertMessage tone="error" icon={<AlertTriangleIcon />}>
            This page needs a reset link from an email. Open it from the message
            we sent you, or request a new one below.
          </AlertMessage>
        </div>

        <p className="mt-[clamp(1.25rem,3dvh,2rem)] text-center text-sm text-neutral-500">
          <Link
            to={ROUTES.forgotPassword}
            className="rounded font-semibold text-brand-600 transition-colors hover:text-brand-700 hover:underline"
          >
            Request a new reset link
          </Link>
        </p>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout badge={<LockIcon />}>
      <header>
        <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
          Account recovery
        </p>
        <h1 className="mt-3 font-display text-[length:clamp(1.65rem,3.4dvh,2.3rem)] leading-[1.12] font-semibold tracking-tight text-neutral-900">
          Set a New <span className="text-brand-500">Password</span>
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-neutral-500">
          Choose a new password for your account. This link stays valid for 30
          minutes from when it was sent.
        </p>
      </header>

      {requestError ? (
        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AlertMessage tone="error" icon={<AlertTriangleIcon />}>
            {requestError}
          </AlertMessage>
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        noValidate
        className="mt-[clamp(1rem,2.5dvh,1.75rem)] space-y-[clamp(0.75rem,2dvh,1.25rem)]"
      >
        <TextField
          label="New password"
          name="password"
          type="password"
          value={password}
          onChange={changePassword}
          icon={<LockIcon />}
          placeholder="At least 8 characters"
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LENGTH}
          error={errors.password}
          footer={<StrengthMeter value={password} />}
        />
        <TextField
          label="Confirm new password"
          name="confirmPassword"
          type="password"
          value={confirmPassword}
          onChange={changeConfirmPassword}
          icon={<LockIcon />}
          placeholder="Re-enter password"
          autoComplete="new-password"
          maxLength={PASSWORD_MAX_LENGTH}
          error={errors.confirmPassword}
        />

        <Button
          type="submit"
          loading={isSubmitting}
          loadingLabel="Resetting…"
          trailingIcon={<ArrowRightIcon />}
        >
          Reset password
        </Button>
      </form>

      <p className="mt-[clamp(1.25rem,3dvh,2rem)] text-center text-sm text-neutral-500">
        <Link
          to={ROUTES.login}
          className="rounded font-semibold text-brand-600 transition-colors hover:text-brand-700 hover:underline"
        >
          Back to sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
