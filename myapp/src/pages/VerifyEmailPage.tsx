/**
 * Email verification landing page.
 *
 * Reached from the link in a verification email after registration. The token
 * travels in the query string (?token=...) and is handed to the backend
 * unchanged for validation. Only the server can tell whether a token is still
 * valid; this page simply shows the outcome.
 */

import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { CheckCircleIcon, AlertTriangleIcon, MailIcon } from '@/components/ui/icons'
import { BRAND_SURFACE } from '@/components/ui/surfaces'
import { ROUTES } from '@/constants/routes'
import { AuthLayout } from '@/Layout/AuthLayout'
import { api, errorMessage } from '@/lib/apiClient'

type VerifyState = 'loading' | 'success' | 'error'

export function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const [state, setState] = useState<VerifyState>(token ? 'loading' : 'error')
  const [message, setMessage] = useState(
    token ? 'Verifying your email...' : 'No verification token provided.',
  )

  useEffect(() => {
    if (!token) return

    let cancelled = false

    async function verify() {
      try {
        await api.postJson('/auth/verify-email', { token })
        if (!cancelled) {
          setState('success')
          setMessage('Your email has been verified. You can now sign in.')
        }
      } catch (err) {
        if (!cancelled) {
          setState('error')
          setMessage(errorMessage(err))
        }
      }
    }

    verify()
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <AuthLayout badge={<MailIcon />}>
      <div className="flex flex-col items-center gap-6 text-center">
        {state === 'loading' ? (
          <div className="size-10 animate-spin rounded-full border-4 border-neutral-200 border-t-brand-500" />
        ) : state === 'success' ? (
          <span className="flex size-14 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
            <CheckCircleIcon className="size-7" />
          </span>
        ) : (
          <span className="flex size-14 items-center justify-center rounded-full bg-rose-50 text-rose-600">
            <AlertTriangleIcon className="size-7" />
          </span>
        )}

        <AlertMessage tone={state === 'success' ? 'success' : state === 'error' ? 'error' : 'info'}>
          {message}
        </AlertMessage>

        {state !== 'loading' && (
          <Link
            to={ROUTES.login}
            className={[BRAND_SURFACE, 'mt-2 inline-block rounded-xl px-6 py-3 text-sm font-semibold'].join(' ')}
          >
            Go to Sign In
          </Link>
        )}
      </div>
    </AuthLayout>
  )
}
