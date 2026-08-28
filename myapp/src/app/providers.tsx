import type { ReactNode } from 'react'
import { BrowserRouter } from 'react-router-dom'

type AppProvidersProps = {
  children: ReactNode
}

/**
 * Every app-wide wrapper lives here, outermost first. Collecting them in one
 * place means adding a query client, a theme context or a toast host later is a
 * one-line change here rather than an edit to App.tsx.
 */
export function AppProviders({ children }: AppProvidersProps) {
  return <BrowserRouter>{children}</BrowserRouter>
}
