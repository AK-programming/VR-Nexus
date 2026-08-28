/**
 * The stand-in for a section that has not been built yet.
 *
 * Every destination in the sidebar is a real route, because a nav item that 404s or
 * bounces you to sign-in is worse than one that admits the page is coming. This says
 * plainly what is missing and offers the way back, which is the whole job.
 *
 * If the URL carries a `q`, it is shown. Today only the dashboard's assistant box
 * sends one, and echoing it is what makes that box demonstrably wired rather than
 * decorative — the question survives the navigation.
 */

import { Link, useSearchParams } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import { QUIET_SURFACE } from '@/components/ui/surfaces'
import { ClockIcon, GridIcon } from '@/components/ui/icons'

type PlaceholderPageProps = {
  title: string
  description: string
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  const [searchParams] = useSearchParams()
  const question = searchParams.get('q')

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md rounded-2xl border border-hairline bg-surface p-8 text-center shadow-sm">
        <span
          aria-hidden="true"
          className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-surface-muted text-neutral-500"
        >
          <ClockIcon className="size-6" />
        </span>

        <h1 className="mt-5 font-display text-xl font-semibold tracking-tight text-neutral-900">
          {title}
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-500">{description}</p>

        {question ? (
          <div className="mt-5 rounded-xl border border-hairline bg-surface-muted px-4 py-3 text-left">
            <p className="text-[0.6875rem] font-semibold tracking-[0.12em] text-neutral-500 uppercase">
              Your question
            </p>
            <p className="mt-1 text-sm text-neutral-800">{question}</p>
          </div>
        ) : null}

        <Link
          to={ROUTES.home}
          className={[
            'mt-6 inline-flex h-11 items-center gap-2 rounded-xl px-4 text-sm font-medium transition-colors duration-150',
            QUIET_SURFACE,
          ].join(' ')}
        >
          <GridIcon className="size-4" />
          Back to dashboard
        </Link>
      </div>
    </div>
  )
}
