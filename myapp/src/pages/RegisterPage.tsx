/**
 * Sign-up.
 *
 * Name, email, password, phone and company all reach the server and are written to
 * the user row. There is deliberately no account-type picker: the public register
 * endpoint always creates a standard user and has no `role` field at all, and
 * nothing in this app currently gates a route by role either (see
 * `require_role` in the backend, defined but unused) — so a picker here would be
 * a choice with no effect, on a shared team workspace where everyone already has
 * access to the same evidence library. If role-gating is ever introduced, an
 * existing administrator promotes an account after it exists, not at sign-up.
 *
 * The rule the whole page follows: show the field, never imply it does something it
 * does not. `toRegisterRequest` is the exact record of what leaves the browser.
 *
 * On success the API returns 201 with the new user and no tokens, so registering
 * cannot sign anyone in. The store records a notice and this page sends them to
 * sign-in, where that notice is waiting.
 */

import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthAlert } from '@/components/feedback/AuthAlert'
import { Button } from '@/components/ui/Button'
import { Checkbox } from '@/components/ui/Checkbox'
import { TextField } from '@/components/ui/TextField'
import {
  ArrowRightIcon,
  BuildingIcon,
  LockIcon,
  MailIcon,
  PhoneIcon,
  UserIcon,
  UserPlusIcon,
} from '@/components/ui/icons'
import { ROUTES } from '@/constants/routes'
import { AuthLayout } from '@/Layout/AuthLayout'
import type { PasswordStrength } from '@/lib/validation'
import {
  measurePasswordStrength,
  validateConfirmPassword,
  validateEmail,
  validateName,
  validateNewPassword,
  validateOptionalPhone,
} from '@/lib/validation'
import {
  COMPANY_MAX_LENGTH,
  NAME_MAX_LENGTH,
  PASSWORD_MAX_LENGTH,
  PHONE_MAX_LENGTH,
} from '@/models'
import type { RegisterFormValues } from '@/models'
import { useAuthStore } from '@/store/authStore'

/** One optional message per field, keyed by the field it belongs to. */
type FieldErrors = Partial<Record<keyof RegisterFormValues, string>>

/* -------------------------------------------------------------------------- */
/* Password strength                                                          */
/* -------------------------------------------------------------------------- */

const STRENGTH_FILL: Record<PasswordStrength['score'], string> = {
  0: 'bg-brand-500',
  1: 'bg-brand-500',
  2: 'bg-amber-500',
  3: 'bg-lime-500',
  4: 'bg-emerald-500',
}

/**
 * Feedback, not a gate — the only rule that blocks submission is the length check.
 * The bars are decoration for the sentence beneath them, which is what carries the
 * information, so only the sentence is exposed to assistive tech.
 */
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

export function RegisterPage() {
  const navigate = useNavigate()

  const register = useAuthStore((state) => state.register)
  const isSubmitting = useAuthStore((state) => state.isSubmitting)
  const failure = useAuthStore((state) => state.failure)
  const clearFailure = useAuthStore((state) => state.clearFailure)

  const [values, setValues] = useState<RegisterFormValues>({
    name: '',
    email: '',
    phone: '',
    company: '',
    password: '',
    confirmPassword: '',
    acceptedTerms: false,
  })
  const [errors, setErrors] = useState<FieldErrors>({})

  /**
   * One patch function instead of eight setters. Errors for the fields being
   * changed are removed with `delete` rather than set to undefined: a computed key
   * from a union of field names widens the object's type, and deleting an optional
   * property sidesteps that entirely. Returning `current` unchanged when there was
   * nothing to clear avoids a re-render on every keystroke.
   */
  function change(changes: Partial<RegisterFormValues>) {
    setValues((current) => ({ ...current, ...changes }))

    setErrors((current) => {
      const next = { ...current }
      let cleared = false

      for (const key of Object.keys(changes)) {
        const field = key as keyof RegisterFormValues
        if (next[field] !== undefined) {
          delete next[field]
          cleared = true
        }
      }

      return cleared ? next : current
    })

    if (failure) {
      clearFailure()
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    const nextErrors: FieldErrors = {
      name: validateName(values.name),
      email: validateEmail(values.email),
      phone: validateOptionalPhone(values.phone),
      password: validateNewPassword(values.password),
      confirmPassword: validateConfirmPassword(values.password, values.confirmPassword),
      acceptedTerms: values.acceptedTerms
        ? undefined
        : 'Accept the terms and privacy policy to continue.',
    }
    setErrors(nextErrors)

    if (Object.values(nextErrors).some(Boolean)) {
      return
    }

    if (await register(values)) {
      /* `replace` so the back button does not return to a filled-in form for an
         account that already exists. The success notice lives in the store, so it
         survives the navigation and greets them on the sign-in screen. */
      navigate(ROUTES.login, { replace: true })
      return
    }

    /* Read straight from the store rather than the `failure` captured above: that
       one is from the render before the request, so it cannot know the outcome. */
    const latest = useAuthStore.getState().failure

    if (latest?.kind === 'conflict') {
      setErrors((current) => ({
        ...current,
        email: 'This email already has an account. Sign in instead.',
      }))
    }
  }

  return (
    <AuthLayout badge={<UserPlusIcon />} width="wide">
      <header>
        <p className="font-display text-[11px] font-semibold tracking-[0.24em] text-brand-500 uppercase">
          Request access
        </p>
        <h1 className="mt-3 font-display text-[length:clamp(1.65rem,3.4dvh,2.3rem)] leading-[1.12] font-semibold tracking-tight text-neutral-900">
          Create Your <span className="text-brand-500">Account</span>
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-neutral-500">
          Set up a VR-Nexus account to start analysing tenders and building your
          evidence library.
        </p>
      </header>

      {failure ? (
        <div className="mt-[clamp(1rem,2.5dvh,1.75rem)]">
          <AuthAlert failure={failure} />
        </div>
      ) : null}

      {/*
        Eight fields will not fit a short laptop no matter how the spacing is set,
        so this form is the one place the layout expects its column to scroll. The
        dvh-based gaps still earn their keep: they buy back roughly 90px on a 700px
        screen, which is often the difference between a short scroll and none.
      */}
      <form
        onSubmit={handleSubmit}
        noValidate
        className="mt-[clamp(1rem,2.5dvh,1.75rem)] space-y-[clamp(0.75rem,2dvh,1.25rem)]"
      >
        <div className="grid gap-x-5 gap-y-[clamp(0.75rem,2dvh,1.25rem)] sm:grid-cols-2">
          <TextField
            label="Full name"
            name="name"
            value={values.name}
            onChange={(name) => change({ name })}
            icon={<UserIcon />}
            placeholder="Ayesha Khan"
            autoComplete="name"
            maxLength={NAME_MAX_LENGTH}
            error={errors.name}
          />
          <TextField
            label="Email address"
            name="email"
            type="email"
            value={values.email}
            onChange={(email) => change({ email })}
            icon={<MailIcon />}
            placeholder="name@company.com"
            autoComplete="email"
            error={errors.email}
          />
        </div>

        <div className="grid gap-x-5 gap-y-[clamp(0.75rem,2dvh,1.25rem)] sm:grid-cols-2">
          <TextField
            label="Phone number"
            name="phone"
            type="tel"
            value={values.phone}
            onChange={(phone) => change({ phone })}
            icon={<PhoneIcon />}
            placeholder="+92 300 1234567"
            autoComplete="tel"
            optional
            maxLength={PHONE_MAX_LENGTH}
            error={errors.phone}
          />
          <TextField
            label="Company"
            name="company"
            value={values.company}
            onChange={(company) => change({ company })}
            icon={<BuildingIcon />}
            placeholder="Your organisation"
            autoComplete="organization"
            optional
            maxLength={COMPANY_MAX_LENGTH}
          />
        </div>

        <div className="grid gap-x-5 gap-y-[clamp(0.75rem,2dvh,1.25rem)] sm:grid-cols-2">
          <TextField
            label="Password"
            name="password"
            type="password"
            value={values.password}
            onChange={(password) => change({ password })}
            icon={<LockIcon />}
            placeholder="At least 8 characters"
            autoComplete="new-password"
            maxLength={PASSWORD_MAX_LENGTH}
            error={errors.password}
            footer={<StrengthMeter value={values.password} />}
          />
          <TextField
            label="Confirm password"
            name="confirmPassword"
            type="password"
            value={values.confirmPassword}
            onChange={(confirmPassword) => change({ confirmPassword })}
            icon={<LockIcon />}
            placeholder="Re-enter password"
            autoComplete="new-password"
            maxLength={PASSWORD_MAX_LENGTH}
            error={errors.confirmPassword}
          />
        </div>

        <Checkbox
          label="I agree to the VR-Nexus terms of service and privacy policy"
          checked={values.acceptedTerms}
          onChange={(acceptedTerms) => change({ acceptedTerms })}
          error={errors.acceptedTerms}
        >
          {/*
            Named but not linked, because there is nowhere yet to link to and a
            dead <a> is worse than plain text. Wrap both in <Link> the moment those
            routes exist.
          */}
          I agree to the{' '}
          <span className="font-medium text-neutral-800">Terms of Service</span> and{' '}
          <span className="font-medium text-neutral-800">Privacy Policy</span>.
        </Checkbox>

        <Button
          type="submit"
          loading={isSubmitting}
          loadingLabel="Creating account…"
          trailingIcon={<ArrowRightIcon />}
        >
          Create account
        </Button>
      </form>

      {/* No "or" divider and no second sign-up method: the form is the only way to
          create an account, and a divider with nothing beyond it is just a rule. */}
      <p className="mt-[clamp(1.25rem,3dvh,2rem)] text-center text-sm text-neutral-500">
        Already have an account?{' '}
        <Link
          to={ROUTES.login}
          className="rounded font-semibold text-brand-600 transition-colors hover:text-brand-700 hover:underline"
        >
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
