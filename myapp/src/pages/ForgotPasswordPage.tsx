/**
 * Forgot password.
 *
 * One field, one outcome: either a reset link goes to the address typed in, or
 * the server says plainly that no account is registered with it. There is no
 * "if this email exists..." hedge here on purpose — see the backend endpoint's
 * own docstring for why that ambiguity is the wrong call for a small internal
 * tool, where a rep who mistyped their address (or never registered) needs a
 * straight answer, not a guessing game.
 *
 * Success does not navigate anywhere. The reset link is only useful once it
 * lands in an inbox, so this screen just confirms the email is on its way and
 * leaves the sign-in link below it as the way back.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/TextField'
import { AlertTriangleIcon, ArrowRightIcon, CheckIcon, MailIcon } from '@/components/ui/icons'
import { ROUTES } from '@/constants/routes'
import { AuthLayout } from '@/Layout/AuthLayout'
import { errorMessage } from '@/lib/apiClient'
import { validateEmail } from '@/lib/validation'
import { authService } from '@/services/authService'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [fieldError, setFieldError] = useState<string | undefined>(undefined)
  const [isSubmitting, setSubmitting] = useState(false)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  function handleEmailChange(value: string) {
    setEmail(value)
    setFieldError(undefined)
    if (requestError) {
      setRequestError(null)
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const nextError = validateEmail(email)
    setFieldError(nextError)
    if (nextError) {
      return
    }

    setSubmitting(true)
    setRequestError(null)

    try {
      const response = await authService.forgotPassword({ email: email.trim() })
      setSuccessMessage(response.message)
    } catch (error) {
      setRequestError(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout badge={<MailIcon />}>
      <header>
        <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
          Account recovery
        </p>
        <h1 className="mt-3 font-display text-[length:clamp(1.65rem,3.4dvh,2.3rem)] leading-[1.12] font-semibold tracking-tight text-neutral-900">
          Forgot Your <span className="text-brand-500">Password?</span>
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-neutral-500">
          Enter the email address on your account and we will send you a link to
          set a new password.
        </p>
      </header>

      {successMessage ? (
        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AlertMessage tone="success" icon={<CheckIcon />}>
            {successMessage}
          </AlertMessage>
        </div>
      ) : null}

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
          label="Email address"
          name="email"
          type="email"
          value={email}
          onChange={handleEmailChange}
          icon={<MailIcon />}
          placeholder="name@company.com"
          autoComplete="email"
          error={fieldError}
          disabled={successMessage !== null}
        />

        <Button
          type="submit"
          loading={isSubmitting}
          loadingLabel="Sending…"
          trailingIcon={<ArrowRightIcon />}
          disabled={successMessage !== null}
        >
          Send reset link
        </Button>
      </form>

      <p className="mt-[clamp(1.25rem,3dvh,2rem)] text-center text-sm text-neutral-500">
        Remembered your password?{' '}
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
