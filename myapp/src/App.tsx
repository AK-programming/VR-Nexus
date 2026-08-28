import { AppProviders } from '@/app/providers'
import { AppRouter } from '@/app/router'

/**
 * Deliberately trivial. App-wide context belongs in app/providers.tsx and the
 * route table in app/router.tsx, so this file should never need to change again.
 */
export default function App() {
  return (
    <AppProviders>
      <AppRouter />
    </AppProviders>
  )
}
