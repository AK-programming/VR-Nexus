/**
 * Route paths in one object so no path string is ever written twice — a link and
 * its <Route> can't drift apart, and renaming a URL is a single edit.
 *
 * `as const` (rather than a TS enum) because tsconfig sets erasableSyntaxOnly,
 * which bans enums: they emit runtime code and so cannot simply be stripped by
 * Vite's transpiler.
 *
 * Every sidebar destination is listed here even though only the dashboard is built.
 * That is deliberate: the router's catch-all sends unknown URLs to sign-in, so a
 * nav item pointing at an unregistered path would throw the user out of the app.
 * The unbuilt ones render a placeholder inside the same shell instead.
 */
export const ROUTES = {
  /** The dashboard, and where a user lands after signing in. */
  home: '/',
  login: '/login',
  register: '/register',

  tenderAnalysis: '/tender-analysis',
  /** Where a tender is added. `/tender-analysis` itself is the listing. */
  tenderUpload: '/tender-analysis/upload',
  /** Live pipeline progress. Takes an optional `?tender=` to focus one of them. */
  tenderProcessing: '/tender-analysis/processing',
  documents: '/documents',
  /** Where a file is added. `/documents` itself is the listing. */
  documentsUpload: '/documents/upload',
  /** Live indexing jobs. Takes an optional `?job=` to focus one of them. */
  documentsProcessing: '/documents/processing',
  assistant: '/ai-assistant',
  activity: '/activity',
  settings: '/settings',
  profile: '/profile',
} as const

export type RoutePath = (typeof ROUTES)[keyof typeof ROUTES]

/**
 * The viewer needs a document id, so it is a function rather than a constant.
 *
 * Two exports for one route because the router and the links need different things:
 * `DOCUMENT_VIEWER_PATTERN` is the `:documentId` form a `<Route path>` matches on,
 * and `documentViewerPath(id)` is the filled-in URL a `<Link to>` navigates to.
 * Deriving the second from the first by string replacement would be clever and would
 * also mean a typo in the pattern silently produced a link to nowhere.
 */
export const DOCUMENT_VIEWER_PATTERN = '/documents/:documentId/view'

export function documentViewerPath(documentId: string): string {
  return `/documents/${documentId}/view`
}

/**
 * The tender analysis workspace needs a tender id, so the same two-export pattern
 * as the document viewer: `TENDER_DETAIL_PATTERN` is the `:tenderId` form a
 * `<Route path>` matches on, and `tenderDetailPath(id)` is the filled-in URL a
 * `<Link to>` navigates to. It is a sibling of the section's index/upload/
 * processing tabs, not a fourth tab, for the same reason the PDF viewer is a
 * sibling of the documents tabs — it is one tender opened for review, not a peer
 * section — so it carries the dashboard shell and a back link rather than the
 * section's segmented control.
 */
export const TENDER_DETAIL_PATTERN = '/tender-analysis/:tenderId'

export function tenderDetailPath(tenderId: string): string {
  return `/tender-analysis/${tenderId}`
}

/**
 * The tender tools workspace needs a tender id, so the same two-export pattern:
 * \`TENDER_TOOLS_PATTERN\` is the \`:tenderId\` form a \`<Route path>\` matches on,
 * and \`tenderToolsPath(id)\` is the filled-in URL a \`<Link to>\` navigates to.
 */
export const TENDER_TOOLS_PATTERN = '/tender-analysis/:tenderId/tools'

export function tenderToolsPath(tenderId: string): string {
  return `/tender-analysis/${tenderId}/tools`
}
