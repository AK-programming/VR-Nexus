import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '@/App'
import { useAuthStore } from '@/store/authStore'
import { applyTheme, getStoredTheme } from '@/lib/theme'
import './index.css'

const rootElement = document.getElementById('root')

// Narrowing rather than a non-null assertion: if index.html ever loses #root,
// this says so instead of failing inside React with a less obvious message.
if (!rootElement) {
  throw new Error('Mount failed: no element with id "root" in index.html')
}

/**
 * Check any restored session before the first render, not from an effect.
 *
 * Two reasons it lives here. StrictMode invokes effects twice in development, so
 * an effect would send two `/me` requests on every load and — because a 401 on
 * either triggers a refresh, and refreshing rotates the refresh token — the second
 * could present a token the first had already spent. And importing the store at
 * the entry point is what guarantees its provider wiring runs before any component
 * can make a request, rather than depending on whichever module happens to import
 * it first.
 *
 * Deliberately not awaited: the app renders immediately with the optimistically
 * restored session, and the guards react when the check resolves. `void` marks the
 * floating promise as intentional — `bootstrap` handles its own failures.
 */
// Stamp the saved theme onto <html> before the first paint, so a dark-mode user
// does not see a flash of the light palette while React boots.
applyTheme(getStoredTheme())

void useAuthStore.getState().bootstrap()

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
