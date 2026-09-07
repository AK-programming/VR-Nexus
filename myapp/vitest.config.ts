/**
 * Vitest configuration.
 *
 * Kept separate from `vite.config.ts` so the build's `tsc -p tsconfig.node.json`
 * (which compiles only `vite.config.ts`) never needs the test dependencies, and
 * `npm run build` stays green whether or not dev dependencies are installed.
 *
 * The suite is deliberately node-environment and pure-logic: it exercises the
 * domain model helpers (status → pipeline stage states, priority derivation,
 * progress normalisation) that decide what the tender screens render, with no
 * DOM and no network. That keeps `npm test` fast and its failures about the code
 * rather than about jsdom. Add `environment: 'jsdom'` and Testing Library here
 * when a component-render test is worth the extra dependencies.
 */
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    globals: false,
  },
})
