/**
 * Renders an auth failure in the tone its reason deserves.
 *
 * Both auth screens need this and both would otherwise reimplement the same
 * mapping, which is how a locked account ends up looking identical to a typo in a
 * password on one screen and not the other.
 *
 * The tones are a judgement about whose fault it is. A wrong password is the
 * user's to fix, so it is red. A lockout or a disabled account is not — they are
 * waiting or asking someone, so red would just be shouting. An unreachable server
 * is nobody's fault and reads as neutral information.
 *
 * Messages come from the server untouched. It is the only party that knows how
 * many minutes are left on a lockout, and rewriting its wording here would mean
 * maintaining two versions of the same sentence.
 */

import type { ReactNode } from 'react'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import type { AlertTone } from '@/components/feedback/AlertMessage'
import {
  AlertTriangleIcon,
  BanIcon,
  ClockIcon,
  InfoIcon,
  SignalOffIcon,
} from '@/components/ui/icons'
import type { AuthFailure } from '@/models'

type Presentation = {
  tone: AlertTone
  title?: string
  icon: ReactNode
}

function present(failure: AuthFailure): Presentation {
  switch (failure.kind) {
    case 'locked':
      return {
        tone: 'warning',
        title: 'Too many sign-in attempts',
        icon: <ClockIcon />,
      }
    case 'expired':
      return {
        tone: 'neutral',
        title: 'You were signed out',
        icon: <ClockIcon />,
      }
    case 'disabled':
      return {
        tone: 'neutral',
        title: 'This account is disabled',
        icon: <BanIcon />,
      }
    case 'offline':
      return { tone: 'neutral', icon: <SignalOffIcon /> }
    case 'validation':
      return { tone: 'error', icon: <InfoIcon /> }
    case 'invalid':
    case 'conflict':
    case 'unknown':
      return { tone: 'error', icon: <AlertTriangleIcon /> }
  }
}

export function AuthAlert({ failure }: { failure: AuthFailure | null }) {
  if (!failure) {
    return null
  }

  const { tone, title, icon } = present(failure)

  return (
    <AlertMessage tone={tone} title={title} icon={icon}>
      {failure.message}
    </AlertMessage>
  )
}
