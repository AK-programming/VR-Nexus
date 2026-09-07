/**
 * Theme (light / dark / follow-system), in one place.
 *
 * The app is built almost entirely on semantic tokens (`bg-surface`,
 * `border-hairline`, `text-neutral-*`), and in Tailwind v4 each of those compiles
 * to `var(--color-…)`. So dark mode is a token swap, not a per-component rewrite:
 * `applyTheme` stamps `data-theme="dark"` on <html>, and `index.css` redefines the
 * surface/field/hairline tokens and inverts the neutral scale under that selector.
 * The branded sidebar keeps its own `ink` tokens and stays dark in both themes.
 *
 * `system` is resolved to light/dark at apply time and re-resolved when the OS
 * preference changes (see themeStore), so there is no third data-theme value to
 * design for. Preference is persisted per browser in localStorage — a personal
 * convenience, wrapped in try/catch because private windows can throw on access.
 */
export type Theme = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'vrnexus.theme'

export function getStoredTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY)
    if (value === 'light' || value === 'dark' || value === 'system') {
      return value
    }
  } catch {
    /* private window / storage blocked — fall through to the default */
  }
  return 'system'
}

export function storeTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    /* best-effort; the in-memory store still reflects the choice this session */
  }
}

export function prefersDark(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  )
}

export function resolveTheme(theme: Theme): ResolvedTheme {
  return theme === 'system' ? (prefersDark() ? 'dark' : 'light') : theme
}

/** Stamp the resolved theme onto <html>. Safe to call before React mounts. */
export function applyTheme(theme: Theme): ResolvedTheme {
  const resolved = resolveTheme(theme)
  const root = document.documentElement
  root.setAttribute('data-theme', resolved)
  root.style.colorScheme = resolved
  return resolved
}
