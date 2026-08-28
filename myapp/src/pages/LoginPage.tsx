/**
 * Sign-in.
 *
 * The form validates only what it can know locally — that an email looks like an
 * email and that a password was typed — then hands off. It deliberately does not
 * check password length here: an existing password is whatever it is, and holding
 * it to today's rules would lock out anyone whose account predates them.
 *
 * One control on this screen describes a capability the API does not have yet:
 * password reset. It is shown, because people look for it, and it says plainly
 * that it is not self-service rather than failing silently when pressed. A control
 * that looks live and does nothing costs more trust than one that explains itself.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { readReturnPath } from '@/app/guards'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { AuthAlert } from '@/components/feedback/AuthAlert'
import { Button } from '@/components/ui/Button'
import { Checkbox } from '@/components/ui/Checkbox'
import { TextField } from '@/components/ui/TextField'
import {
  ArrowRightIcon,
  CheckIcon,
  InfoIcon,
  LockIcon,
  MailIcon,
  ShieldCheckIcon,
} from '@/components/ui/icons'
import { ROUTES } from '@/constants/routes'
import { AuthLayout } from '@/Layout/AuthLayout'
import { validateEmail, validatePasswordPresent } from '@/lib/validation'
import type { LoginFormValues } from '@/models'
import { useAuthStore } from '@/store/authStore'

type FieldErrors = {
  email?: string
  password?: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()

  /* Selected one field at a time. A selector that returned an object literal
     would produce a new reference on every store change and re-render this page
     for updates it does not care about. */
  const login = useAuthStore((state) => state.login)
  const isSubmitting = useAuthStore((state) => state.isSubmitting)
  const failure = useAuthStore((state) => state.failure)
  const clearFailure = useAuthStore((state) => state.clearFailure)
  const notice = useAuthStore((state) => state.notice)

  const [values, setValues] = useState<LoginFormValues>({
    email: '',
    password: '',
    remember: false,
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [isResetHelpOpen, setResetHelpOpen] = useState(false)

  /**
   * Editing a field clears that field's error and any failure from the last
   * attempt. Leaving "Incorrect email or password" on screen while someone is busy
   * correcting it is just noise, and the guard means a keystroke only writes to the
   * store when there is actually something to clear.
   *
   * Written out per field rather than as one generic setter: a computed key taken
   * from `keyof LoginFormValues` widens the resulting object type and turns a
   * straightforward state update into a typing puzzle for no gain at three fields.
   */
  function dismissFailure() {
    if (failure) {
      clearFailure()
    }
  }

  function setEmail(value: string) {
    setValues((current) => ({ ...current, email: value }))
    setErrors((current) => ({ ...current, email: undefined }))
    dismissFailure()
  }

  function setPassword(value: string) {
    setValues((current) => ({ ...current, password: value }))
    setErrors((current) => ({ ...current, password: undefined }))
    dismissFailure()
  }

  function setRemember(checked: boolean) {
    setValues((current) => ({ ...current, remember: checked }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const nextErrors: FieldErrors = {
      email: validateEmail(values.email),
      password: validatePasswordPresent(values.password),
    }
    setErrors(nextErrors)

    if (nextErrors.email || nextErrors.password) {
      return
    }

    if (await login(values)) {
      navigate(readReturnPath(location.state), { replace: true })
    }
  }

  return (
    <AuthLayout badge={<ShieldCheckIcon />}>
      <header>
        <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
          Secure sign-in
        </p>
        {/* Sized in dvh rather than at a width breakpoint, because what decides
            whether this heading has room is the height of the screen, not how wide
            it is. A 1366×768 laptop is wide enough for the largest size and far too
            short for it.

            The `length:` hint is there because text-[…] is ambiguous — Tailwind has
            to decide between font-size and colour — and naming the type means it
            never has to infer that from a clamp(). */}
        <h1 className="mt-3 font-display text-[length:clamp(1.65rem,3.4dvh,2.3rem)] leading-[1.12] font-semibold tracking-tight text-neutral-900">
          Welcome <span className="text-brand-500">Back</span>
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-neutral-500">
          Pick up your tender analysis where you left it.
        </p>
      </header>

      {notice ? (
        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AlertMessage tone="success" icon={<CheckIcon />}>
            {notice}
          </AlertMessage>
        </div>
      ) : null}

      {failure ? (
        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AuthAlert failure={failure} />
        </div>
      ) : null}

      {/*
        Every gap from here down is a clamp on dvh, so the form compresses on a
        short laptop and opens back up on a tall monitor rather than holding one
        fixed rhythm and producing a scrollbar on half the screens it meets. The
        floors are the tightest spacing that still reads as separate groups.
      */}
      <form
        onSubmit={handleSubmit}
        noValidate
        className="mt-[clamp(1rem,2.5dvh,1.75rem)] space-y-[clamp(0.75rem,2dvh,1.25rem)]"
      >
        <TextField
          label="Email address"
          name="email"
          type="email"
          value={values.email}
          onChange={setEmail}
          icon={<MailIcon />}
          placeholder="name@company.com"
          autoComplete="email"
          error={errors.email}
        />

        <TextField
          label="Password"
          name="password"
          type="password"
          value={values.password}
          onChange={setPassword}
          icon={<LockIcon />}
          placeholder="Enter your password"
          autoComplete="current-password"
          error={errors.password}
        />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <Checkbox
            label="Keep me signed in on this device"
            checked={values.remember}
            onChange={setRemember}
          >
            Keep me signed in
          </Checkbox>

          <button
            type="button"
            onClick={() => setResetHelpOpen((open) => !open)}
            aria-expanded={isResetHelpOpen}
            className="rounded text-sm font-medium text-brand-600 transition-colors hover:text-brand-700 hover:underline"
          >
            Forgot password?
          </button>
        </div>

        {isResetHelpOpen ? (
          <AlertMessage tone="info" icon={<InfoIcon />}>
            Password resets aren&rsquo;t self-service yet. Ask a VR-Nexus
            administrator to reset yours, and you&rsquo;ll be able to sign in
            straight away.
          </AlertMessage>
        ) : null}

        <Button
          type="submit"
          loading={isSubmitting}
          loadingLabel="Signing in…"
          trailingIcon={<ArrowRightIcon />}
        >
          Sign in
        </Button>
      </form>

      {/* Sign in is the only way in, so there is no "or" divider and no second
          method beneath it — a divider with nothing on the far side of it is just a
          rule. This link is the one thing that follows the button. */}
      <p className="mt-[clamp(1.25rem,3dvh,2rem)] text-center text-sm text-neutral-500">
        New to VR-Nexus?{' '}
        <Link
          to={ROUTES.register}
          className="rounded font-semibold text-brand-600 transition-colors hover:text-brand-700 hover:underline"
        >
          Create an account
        </Link>
      </p>
    </AuthLayout>
  )
}
