/**
 * Barrel for the domain models, so callers write
 * `import type { User } from '@/models'` instead of reaching for a filename.
 *
 * `export *` rather than a named list: it carries types and values alike, which
 * a `export { ... }` list cannot do under verbatimModuleSyntax without splitting
 * into two statements that then have to be kept in sync by hand.
 */
export * from './auth'
