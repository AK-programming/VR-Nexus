import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

/**
 * Scoped to .js/.jsx on purpose.
 *
 * Linting .ts/.tsx needs the typescript-eslint parser, whose peer range does not
 * yet admit ESLint 10 (installed here) — adding it makes `npm install` fail
 * outright. Until that lands, `npm run typecheck` is the safety net, and it
 * catches strictly more than the lint rules would: unused locals, unreachable
 * imports, and every type error.
 *
 * To enable it later: `npm i -D typescript-eslint`, then add
 * `files: ['**\/*.{ts,tsx}']` with `extends: [tseslint.configs.recommended]`.
 */
export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
])
