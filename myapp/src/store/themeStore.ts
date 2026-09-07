/**
 * The theme choice, as a tiny Zustand store so any component can read the current
 * setting and the Settings screen can change it.
 *
 * `setTheme` does three things in lock step: persist the choice, stamp it onto
 * <html>, and update the store so the UI (the active state of the theme buttons)
 * reflects it. A one-time listener keeps `system` honest: when the OS flips
 * light/dark and the user is on `system`, we re-apply so the page follows.
 */
import { create } from 'zustand'
import { applyTheme, getStoredTheme, resolveTheme, storeTheme } from '@/lib/theme'
import type { ResolvedTheme, Theme } from '@/lib/theme'

type ThemeState = {
  theme: Theme
  resolved: ResolvedTheme
  setTheme: (theme: Theme) => void
}

const initial = getStoredTheme()

export const useThemeStore = create<ThemeState>((set) => ({
  theme: initial,
  resolved: resolveTheme(initial),
  setTheme: (theme) => {
    storeTheme(theme)
    const resolved = applyTheme(theme)
    set({ theme, resolved })
  },
}))

if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    const { theme, setTheme } = useThemeStore.getState()
    if (theme === 'system') {
      setTheme('system')
    }
  })
}
