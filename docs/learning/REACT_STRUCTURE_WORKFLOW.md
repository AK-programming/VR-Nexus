# React Project Structure and Workflow, Taught Through VR-Nexus

This document has a narrower job than a file-by-file catalog. It is about the *shape* of a real React project: why the folders are the ones they are, how a request actually moves through them from a click to a rendered pixel, and what decisions you should copy into your own future projects because they generalize well beyond this one app. The worked example throughout is the VR-Nexus frontend: React 19, Vite, TypeScript, React Router 7 (used in its classic `<Routes>`/`<Route>` form, not the newer data-router API), and Tailwind CSS v4. Every claim below was checked against the actual source files at `myapp/src`, not assumed from convention.

If you have already read `FRONTEND_EXPLAINED.md`, treat this as the companion piece that answers a different question. That document tells you what each file does. This one tells you why the folders exist as boundaries, how data actually flows across them on a real page load, and what to steal for your own project.

## 1. The folder tree

```
src/
├── main.tsx              # entry point: applies saved theme, starts auth bootstrap, mounts <App/>
├── App.tsx                # trivial root: wraps AppRouter in AppProviders, nothing else
├── index.css               # Tailwind v4 @theme tokens (colors, fonts) and the dark-mode variant
├── vite-env.d.ts            # ambient types for import.meta.env (VITE_API_BASE_URL)
│
├── app/                    # wiring that is app-wide, not feature-specific
│   ├── router.tsx           # the one route table: every URL in the app, in one file
│   ├── providers.tsx         # app-wide context providers (today: just <BrowserRouter>)
│   └── guards.tsx            # RequireAuth / RedirectIfAuthenticated route guards
│
├── constants/
│   └── routes.ts             # ROUTES object plus URL-pattern builders (tenderDetailPath, etc.)
│
├── Layout/                  # shells that wrap pages: chrome that is rendered once per section
│   ├── AuthLayout.tsx          # split-panel shell for login/register/forgot/reset
│   ├── DashboardLayout.tsx      # sidebar + header + footer shell for the whole signed-in app
│   ├── DocumentsLayout.tsx       # heading + tab bar shared by the three Documents screens
│   └── TenderAnalysisLayout.tsx   # heading + tab bar shared by the three Tender Analysis screens
│
├── pages/                   # one component per route, the thing the router actually renders
│   ├── LoginPage.tsx, RegisterPage.tsx, ForgotPasswordPage.tsx, ResetPasswordPage.tsx
│   ├── DashboardPage.tsx, ActivityPage.tsx, SettingsPage.tsx, ProfilePage.tsx
│   ├── DocumentsOverviewPage.tsx, UploadDocumentsPage.tsx, ProcessingPage.tsx, PdfViewerPage.tsx
│   ├── TenderOverviewPage.tsx, UploadTenderPage.tsx, TenderProcessingPage.tsx,
│   │   TenderReviewPage.tsx, TenderToolsPage.tsx
│   └── AiAssistantPage.tsx, AboutPage.tsx, HomePage.tsx
│
├── components/              # everything a page renders that is not the page itself
│   ├── dashboard/              # widgets specific to the home dashboard and the app chrome
│   │   (Header, Sidebar, Footer, Panel, StatCard, AnalysisOverview, StorageMeter, ...)
│   ├── documents/               # widgets specific to the evidence-library feature
│   │   (DocumentDropzone, ProcessingTimeline, JobStagePill, TrainingStatusPill, FileGlyph)
│   ├── tender/                   # widgets specific to the tender-analysis feature
│   │   (TenderDropzone, TenderTimeline, RequirementReviewCard, ComplianceMatrix,
│   │    EvaluationSimulator, RiskScanner, SubmissionChecker, ReassignDialog, ...)
│   ├── feedback/                  # generic, feature-agnostic status and error display
│   │   (AlertMessage, AuthAlert, DataState: LoadingRows/ErrorBlock/StaleDataNotice/AsyncSection)
│   └── ui/                        # the shared component kit: no feature knowledge at all
│       (ActionButton, Button, TextField, Checkbox, DataTable, ConfirmDialog, icons.tsx, ...)
│
├── hooks/                    # reusable stateful logic, shared across pages
│   ├── useAsyncData.ts          # generic "fetch, track loading/error, allow refetch" hook
│   ├── useJobProgress.ts         # WebSocket-plus-polling hook for library indexing jobs
│   └── useTenderProgress.ts       # WebSocket-plus-polling hook for the tender pipeline
│
├── services/                  # the only code that knows backend endpoint paths and shapes
│   ├── authService.ts             # /api/auth/* : login, register, refresh, me, password reset
│   ├── documentService.ts          # /api/documents/* and the library indexing jobs
│   └── tenderService.ts             # /api/tenders/* : upload, list, review, finalize, ws-ticket
│
├── lib/                       # low-level, feature-agnostic utility code
│   ├── apiClient.ts               # the ONE place fetch() is called; auth headers, retry, errors
│   ├── formatting.ts               # date/number/byte display helpers
│   ├── theme.ts                     # light/dark/system theme resolution and persistence
│   ├── validation.ts                 # client-side form validation functions
│   └── pdfWorker.ts                   # one-time react-pdf/pdf.js worker setup
│
├── store/                     # cross-cutting client state, readable from outside React
│   ├── authStore.ts                # zustand store: signed-in user, tokens, auth actions
│   ├── authStorage.ts               # hand-rolled localStorage/sessionStorage persistence
│   └── themeStore.ts                 # zustand store: theme preference and resolved theme
│
└── models/                    # TypeScript types describing the backend's data shapes
    ├── auth.ts                     # User, LoginRequest, TokenResponse, AuthFailure, ...
    ├── dashboard.ts                  # UI-only aggregate types the dashboard assembles client-side
    ├── documents.ts                   # library document, job, and stage types + helpers
    ├── tenders.ts                      # tender, requirement, evidence-match types + helpers
    └── index.ts                         # barrel re-exporting auth.ts only
```

## 2. What each folder is for, and why it stays separate

**`app/`** holds the wiring that makes the app an app: the route table, the top-level providers, the route guards. Nothing here knows about tenders or documents specifically. It holds exactly three things: where every URL goes (`router.tsx`), what wraps the whole tree (`providers.tsx`), and who is allowed to see what (`guards.tsx`). No page-specific logic belongs here; `router.tsx`'s own comments call itself "the one place a route is declared." A route table you cannot read in one sitting is one nobody trusts, and once page logic leaks into it you lose the single file that shows, at a glance, which URLs exist and which are protected.

**`Layout/`** holds shared chrome, the shell a group of pages sits inside, never a page's own content. `DashboardLayout` renders the sidebar, header, and footer once and gives every signed-in page an `<Outlet/>`; `DocumentsLayout` and `TenderAnalysisLayout` do the same one level down, each owning a heading and tab bar for its own three-screen section. Anything a single page needs and no other page shares belongs in `components/` instead. A layout that starts absorbing page-specific logic stops being reusable, and chrome ends up duplicated anyway to avoid fighting a layout grown too many special cases.

**`app/` and `Layout/` together are why `router.tsx` stays small**: the router only ever nests a page inside a layout and never re-implements a layout's own markup, the whole payoff of nested layout routes covered in section 4.

**`components/`**, split into `dashboard/`, `documents/`, `feedback/`, `tender/`, and `ui/`, is the clearest lesson here about scaling a component tree. `dashboard/`, `documents/`, and `tender/` are feature-grouped: everything in `tender/` (`TenderDropzone`, `ComplianceMatrix`, `RequirementReviewCard`, `RiskScanner`) exists because of the tender-analysis feature and would be deleted wholesale if that feature were removed. `ui/` is the opposite: `ActionButton`, `TextField`, `DataTable`, `icons.tsx` know nothing about tenders or documents; they are a small internal kit any feature can reach for. `feedback/` sits between the two: `AlertMessage` and the `DataState` trio (`LoadingRows`, `ErrorBlock`, `StaleDataNotice`) are generic, but grouped separately because they solve the recurring "show the state of an async operation" problem, distinct from pure input controls. The rule that keeps this from decaying: before adding a component, ask whether it is reusable with no feature knowledge (`ui/`), reusable for the same cross-cutting problem everywhere (`feedback/`), or specific to one feature (a named subfolder). Get it wrong and the cost is real: a `TenderDropzone` in `ui/` invites reuse of something that secretly assumes tender-shaped data; an `ActionButton` buried in `tender/` gets reinvented by the next feature because nobody thought to look there.

**`constants/`** holds pure, static data, chiefly `ROUTES`, the single object of every URL string plus pattern-and-builder pairs (`TENDER_DETAIL_PATTERN` and `tenderDetailPath(id)`) for routes carrying an ID. Nothing computed or runtime-dependent belongs here. Both the router and ordinary pages reference the same path strings, and a shared, dependency-free module is what guarantees a `<Link to="/tender-analysis/upload">` typed by hand can never drift from the `<Route path="upload">` in the router; both build from `ROUTES.tenderUpload` instead.

**`hooks/`** holds reusable stateful logic not tied to one page: `useAsyncData`, the general-purpose data-loading hook nearly every page uses, and `useJobProgress`/`useTenderProgress`, the WebSocket-plus-polling hooks. It holds logic that calls React's built-in hooks internally and packages up behavior more than one component needs, not one-off state a single component owns privately (plain `useState`), and not direct backend calls that bypass `services/`. A hook is where "loading, error, refetch" or "socket, poll, reconnect" gets solved once, correctly, under real edge cases (a slow network, a cancelled navigation, a dropped socket); solved inline in every page, it gets solved, and slightly mis-solved, five separate times.

**`lib/`** holds low-level, feature-agnostic utilities: `apiClient.ts` (the only file that calls `fetch()`), `formatting.ts`, `theme.ts`, `validation.ts`, `pdfWorker.ts`. Code here has no opinion about tenders, documents, or any specific screen; a `lib/` function could be lifted into an unrelated project unchanged. It knows no backend endpoint path (that is `services/`) and reads no application state like the signed-in user (that is `store/`). This is what lets `apiClient.ts` stay genuinely reusable: it does not import `authStore.ts` directly (a circular import, since the store also calls the API), so the store instead hands the client two functions, `setAuthTokenProvider` and `setUnauthorizedHandler`, at the store's own module load time. `lib/` stays clean of app-specific knowledge, and the dependency runs one way at runtime even though the two logically depend on each other.

**`models/`** holds TypeScript types and small pure normalizing functions describing exactly what crosses the wire to and from the FastAPI backend: `User`, `LoginRequest`, `TenderDetail`, `Requirement`, `EvidenceMatch`, derived union types like `TenderStatus`, and helpers like `progressFromDetail()`. These files render nothing and call no network function. The payoff is concrete: `services/tenderService.ts` imports its return types from `models/tenders.ts`, so a backend field rename fails to typecheck immediately, in your editor, rather than surfacing as a silent `undefined` a user finds weeks later.

**`pages/`** holds one component per route, the thing `router.tsx` actually mounts. A page's job is composition: call a hook or two for data, hand that data to `components/`, wire up handlers. A large, reusable visual building block used by more than one screen belongs in `components/`, and raw fetching belongs in `services/`, not here. A page that grows its own fetch logic, its own child component definitions, and its own validation becomes unreadable as a unit; a page that is mostly composition (call `useAsyncData`, render an `AsyncSection`, render a list of `RequirementReviewCard`) stays legible even at hundreds of lines, because each delegated piece is independently understandable.

**`services/`** holds the only code that knows an actual backend URL path and request/response shape for one resource: `authService.ts` knows `/api/auth/login`, `tenderService.ts` knows `/api/tenders`. It holds thin, named async functions per operation (`uploadTender`, `getTender`, `finalizeTender`), not the mechanics of making an HTTP request (`lib/apiClient.ts`'s job) and no UI state. This split, services knowing "what can I ask the server" and `apiClient.ts` knowing "how do I make a request," lets you change how requests are made (deduplication, retry policy, transport) in exactly one file, touching no page or service function.

**`store/`** holds cross-cutting client state many unrelated parts of the tree need to read or change, readable outside a component's own render cycle: `authStore.ts` (signed-in user, tokens, submit/loading flags) and `themeStore.ts` (theme preference). It holds state that would otherwise force prop-drilling through layers that do not themselves care, or that a non-component module like `apiClient.ts` needs via `getState()`; state private to one component and its children stays as local `useState`. A store that accumulates everything "just in case" becomes a second, competing source of truth harder to reason about than local state, while no store at all forces awkward prop-passing the moment two distant components need the same value.

## 3. How a request flows end to end

### 3a. A user logs in

1. The browser requests `/login`. `src/app/router.tsx` matches `ROUTES.login` and renders `<RedirectIfAuthenticated><LoginPage/></RedirectIfAuthenticated>`, outside the `RequireAuth`-wrapped `DashboardLayout` block, so no sidebar or header exists yet; `LoginPage` wraps its own content in `AuthLayout`, the split-panel shell shared by all four auth screens.

2. `LoginPage.tsx` reads individual fields from the auth store: `useAuthStore((state) => state.login)`, `.isSubmitting`, `.failure`, `.notice`. Form values (`email`, `password`, `remember`) live in local `useState`, private to this one screen.

3. The user types and submits. `handleSubmit` runs client-side checks (`validateEmail`, `validatePasswordPresent` from `lib/validation.ts`) and, if they pass, calls `login(values)`, the `login` action from `useAuthStore`.

4. `authStore.ts`'s `login` action sets `isSubmitting: true`, then calls `authService.login(toLoginRequest(values))`. `authService.ts` posts to `AUTH_ENDPOINTS.login` (`/api/auth/login`) through `api.postJson`, with `anonymous: true` so no stale token rides along on a request that is, by definition, from someone not yet signed in.

5. `api.postJson` lives in `lib/apiClient.ts`, the single file that calls `fetch()`. It sends the request to `${API_BASE_URL}/api/auth/login` (in development, `API_BASE_URL` is empty, so this is a relative path Vite's dev proxy forwards to the backend at `127.0.0.1:8000`), and returns parsed JSON or throws a typed `ApiError`.

6. On success, `authService.login` runs the response through `normalizeUser()` before returning a `TokenResponse` (`user`, `access_token`, `refresh_token`) to the store.

7. `authStore.ts`'s `login` action calls `writeStoredSession()` (`store/authStorage.ts`) to persist the session to `localStorage` or `sessionStorage` depending on "remember me," then calls Zustand's `set()` with the new `user`, `accessToken`, `refreshToken`, `isSubmitting: false`. This `set()` is the moment every subscribed component re-renders.

8. `login()` resolves `true`. `handleSubmit` calls `navigate(readReturnPath(location.state), { replace: true })`. `readReturnPath` (`app/guards.tsx`) reads the `from` path `RequireAuth` stashed before redirecting the unauthenticated visitor to `/login`, refusing anything that does not start with a single `/` (closing an open-redirect hole), so the user lands back where they were headed, defaulting to `ROUTES.home`.

9. React Router re-evaluates `app/router.tsx`. The target route sits inside `<RequireAuth><DashboardLayout/></RequireAuth>`. `RequireAuth` reads `selectIsAuthenticated(state)`, now `true`, and renders `DashboardLayout` with the matched page filling its `<Outlet/>`.

10. From here, every authenticated request reads the current token through the getter `authStore.ts` registered via `apiClient.setAuthTokenProvider(() => useAuthStore.getState().accessToken)` at module load, attached as `Authorization: Bearer <token>` inside `request()`. If a request comes back `401` (the access token expires after 24 hours), `apiClient.ts` calls the handler registered via `setUnauthorizedHandler`, `refreshSession()`, which trades the refresh token for a new pair and transparently replays the original request once. No page or service ever thinks about this.

### 3b. A user uploads a tender and watches live progress

1. The user navigates to `/tender-analysis/upload` (`ROUTES.tenderUpload`), nested inside `<Route path={ROUTES.tenderAnalysis} element={<TenderAnalysisLayout/>}>`, so `TenderAnalysisLayout` renders once and `UploadTenderPage` fills its `<Outlet/>`.

2. `UploadTenderPage.tsx` renders `TenderDropzone` (`components/tender/`), a single-file dropzone restricted to PDF via `TENDER_DROPZONE_ACCEPT` in `models/tenders.ts`. Dropping a file calls `handleFileAccepted`, storing the `File` in local `useState`; nothing is sent yet.

3. The user optionally fills details (reference, authority, deadline, kept as `TenderUploadMetadata` in local state), then presses "Upload & analyse." `handleSubmit` first calls `uploadTender(file)` (`services/tenderService.ts`), which builds a `FormData` and posts via `api.postForm(BASE, body)` (`BASE` is `/api/tenders`), deliberately omitting `Content-Type` so the browser sets the multipart boundary itself.

4. The backend stores the file, creates the tender row, and enqueues the analysis pipeline in one call, returning the new id in milliseconds. If metadata was typed, a second call, `updateTender(id, patch)`, `PATCH`es it via `api.patchJson`; a failure here does not undo the upload, it just carries a warning forward.

5. `handleSubmit` calls `navigate(\`${ROUTES.tenderProcessing}?tender=${id}\`, ...)`, sending the user to `/tender-analysis/processing?tender=<id>`.

6. `TenderProcessingPage.tsx` mounts, calling `useAsyncData((signal) => listTenders({ limit: 100 }, { signal }), [])` to read every currently-live tender (a bounded window, not a dedicated queue endpoint), and reads `?tender=` via `useSearchParams` to pick which one is focused; an unmatched id falls back to the first row rather than erroring.

7. The focused tender is handed to a `TenderWatcher` subcomponent, where `useTenderProgress(tender.id, { initialProgress: seed })` is actually called (`hooks/useTenderProgress.ts`). Seeded from the list row's last known status, the panel renders something real the instant it mounts, before any connection exists.

8. Inside `useTenderProgress`, an effect keyed on `tenderId` first calls `mintTenderWsTicket(tenderId)`, an ordinary authenticated `POST /api/tenders/{id}/ws-ticket` returning a short-lived, single-use ticket. This exists because a browser cannot attach an `Authorization` header to a `WebSocket` handshake, so the ticket travels in the socket's query string instead.

9. With the ticket, the hook opens `new WebSocket(tenderProgressUrl(tenderId, ticket))`, built via `websocketUrl()` in `apiClient.ts` as `ws://` or `wss://` against the page's own origin; in development, Vite proxies `/ws` to `ws://127.0.0.1:8000`, exactly mirroring the `/api` proxy, so the whole app talks to one origin regardless of transport.

10. As the pipeline advances, the backend pushes frames down the socket. `ws.onmessage` parses each frame, converts it with `progressFromFrame()` into a normalized `TenderProgress`, and calls `setProgress(next)`. That state update re-renders `TenderWatcher`, which passes fresh `status`, `percent`, and `message` into `TenderTimeline`, so the stage rail and status text update live, no polling, no reload.

11. If the socket cannot be sustained, `ws.onerror`/`ws.onclose` calls `startPolling()`, which calls `getTender(tenderId)` every two seconds and feeds the same `record()` function, so the UI degrades to polling without `TenderWatcher` knowing which transport is active; it only sees `progress`, `failedAt`, and `connection` (`'idle' | 'live' | 'polling' | 'offline' | 'closed'`).

12. When the tender reaches a socket-terminal status (`finalized` or `failed`; `ready_for_review` is deliberately not terminal, since the socket stays open through human review), the hook sets `connection` to `'closed'` and an effect in `TenderWatcher` calls `onFinished`, which is `tenders.refetch`, so the queue list beside the focused panel refreshes.

## 4. How routing and layouts nest

`src/app/router.tsx` is the single source of truth for every URL, and it is worth reading start to finish once, because the whole nesting story is visible in one file. The four unauthenticated routes (`/login`, `/register`, `/forgot-password`, `/reset-password`) are declared first, flat, with no shared layout route wrapping them (each page instead wraps itself in `AuthLayout` individually, since the two forms need different column widths). Everything else hangs off one pathless route:

```
<Route element={<RequireAuth><DashboardLayout/></RequireAuth>}>
  <Route path={ROUTES.home} element={<DashboardPage/>} />
  <Route path={ROUTES.tenderAnalysis} element={<TenderAnalysisLayout/>}>
    <Route index element={<TenderOverviewPage/>} />
    <Route path="upload" element={<UploadTenderPage/>} />
    <Route path="processing" element={<TenderProcessingPage/>} />
  </Route>
  <Route path={TENDER_DETAIL_PATTERN} element={<TenderReviewPage/>} />
  <Route path={TENDER_TOOLS_PATTERN} element={<TenderToolsPage/>} />
  <Route path={ROUTES.documents} element={<DocumentsLayout/>}>
    <Route index element={<DocumentsOverviewPage/>} />
    <Route path="upload" element={<UploadDocumentsPage/>} />
    <Route path="processing" element={<ProcessingPage/>} />
  </Route>
  <Route path={DOCUMENT_VIEWER_PATTERN} element={<PdfViewerPage/>} />
  <Route path={ROUTES.assistant} element={<AiAssistantPage/>} />
  ... (activity, settings, profile)
</Route>
<Route path="*" element={<Navigate to={ROUTES.login} replace />} />
```

This is two levels of layout nesting. The outer route, with no `path` of its own, has `RequireAuth` wrapping `DashboardLayout` as its `element`; because a parent route with no path still needs to render, and every child route below it renders inside `DashboardLayout`'s own `<Outlet/>`. That is what a layout route buys you: `DashboardLayout` (sidebar, header, footer) is written and mounted exactly once, and it survives every navigation between the pages nested under it, rather than being torn down and rebuilt on each link. Compare that to the alternative of every page importing and rendering its own copy of `<Sidebar/>` and `<Header/>`: not only is that more code, it also means the sidebar's own state (whether it is collapsed, whether the mobile drawer is open) would either have to live in a store just to survive a navigation, or reset itself unnecessarily on every single page change.

One level deeper, `TenderAnalysisLayout` and `DocumentsLayout` repeat the same trick for their own three-tab sections: each is mounted once at `/tender-analysis` or `/documents`, draws its own heading and segmented tab control exactly once, and its three children (`index`, `upload`, `processing`) fill its `<Outlet/>` in turn. The `index` route (rather than a repeated `/tender-analysis` path on the child) is what lets the parent own the URL outright, so the child route can never register a conflicting path for the same location.

Notice what is deliberately *not* nested a third level down: the tender detail page (`TENDER_DETAIL_PATTERN = '/tender-analysis/:tenderId'`) and the tender tools page (`TENDER_TOOLS_PATTERN`) sit as flat siblings directly under `DashboardLayout`, not as a fourth tab inside `TenderAnalysisLayout`. The router's own comments explain the reasoning: nesting them as a tab would visually suggest you can tab away from a specific tender's review screen and tab back to it as if it were a peer of "Overview" and "Upload," when the real navigation model is "open one tender, then go back to the list." The same logic keeps the PDF viewer (`DOCUMENT_VIEWER_PATTERN`) out of `DocumentsLayout`'s tabs. This is the general lesson: nesting should mirror the actual navigation model a user experiences, not just the file's location on disk; a route that behaves like "one specific item opened for reading" belongs as a sibling with a back link, not as a peer of a section's real tabs.

`app/guards.tsx` is what makes `RequireAuth` actually enforce authentication before that shared layout renders at all: it reads `selectIsAuthenticated` off `authStore`, and if that is false, it renders a `<Navigate to={ROUTES.login} .../>` instead of its children, so `DashboardLayout` and everything nested inside it never mount for a signed-out visitor. Because the guard sits at the layout route's `element`, and not repeated inside each individual page, a new page added anywhere under that route inherits the protection automatically; there is no page that can forget to check whether someone is signed in, because the check never lived in the page to begin with.

## 5. State management map

VR-Nexus uses four distinct places for state, and the choice of which one to use for a new piece of state is not arbitrary; it follows from one question: who else needs to read this, and does it need to survive outside a component's own lifecycle?

**Local component state (`useState`)** is for anything private to one screen and its own children: the text typed into `LoginPage`'s form fields, whether `UploadTenderPage`'s details panel is expanded, which row a confirm dialog is currently asking about. Nothing outside that component tree ever reads it, and it disappears the moment the component unmounts, which is exactly correct for a half-typed form field nobody else in the app should see.

**Custom hooks (`useAsyncData`, `useJobProgress`, `useTenderProgress`)** are for state that is genuinely local to one component's use of it, but whose *logic* (not the data itself) needs to be identical everywhere it is used. `useAsyncData` is called separately by every page that loads data; each call produces its own independent `status`/`data`/`error` state, but the rules for that state (an `AbortController` per request, keeping stale data visible during a background refresh, telling a true first load from a refetch) are written once and reused. The same applies to the two progress hooks: each call to `useTenderProgress` opens its own socket and owns its own `progress`/`connection` state, but the state machine those values move through, and every edge case around a dropped connection, is defined a single time.

**The zustand stores in `store/`** are for state that many unrelated components across the tree need to read or write, or that a plain module (not a component at all) needs to reach into directly. The signed-in user and their tokens are the clearest case: the sidebar needs the user's name, the API client needs the token on every request, and a login form far away in the tree needs to set all of it at once. `themeStore` is smaller but the same shape: the theme toggle button and the very first paint of `<html>` both need the current theme. The test for "does this belong in a store" is whether passing it down as props would mean threading it through components that do not themselves use it, purely to hand it to a descendant that does, or whether something outside React's component tree (`apiClient.ts`) needs to read it via `getState()`.

**Server state fetched fresh via `services/`** is, deliberately, not cached or centrally stored at all in this app. There is no query-caching library; every page that needs tender or document data calls a service function through `useAsyncData` on its own, and gets a fresh answer. This is a real design choice, not an oversight: `app/providers.tsx`'s own comment marks itself as the future home for a shared query client if one is ever needed, which tells you the team considered it and decided the app is not yet big enough, with enough duplicated fetches across screens, to justify the added complexity. That is the right default for a beginner's own project too: reach for a caching layer when you can point at actual duplicated network calls it would remove, not before.

The reasoning a beginner should carry forward: default to `useState`. Reach for a custom hook only once you notice you are about to write the *same* loading-or-socket logic in a second component. Reach for a store only when a value genuinely needs to be read from two places that are not parent and child, or from outside React entirely. And do not build a caching layer for server data until duplicated fetching is an actual, observed problem, not a hypothetical one.

## 6. Build and dev tooling, briefly

`vite.config.ts` registers the React and Tailwind v4 plugins, sets the `@` import alias to `./src`, and configures a dev-server proxy: any request to `/api/*` is forwarded to `http://127.0.0.1:8000`, and any request to `/ws/*` is forwarded the same way with `ws: true` set so WebSocket upgrades are proxied too. This one setting is what makes the whole "authenticated WebSocket, same-origin API" story in section 3b work without any special-casing in application code: the browser only ever talks to `localhost:5173` (the Vite dev server), for both REST calls and WebSocket connections, so there is no cross-origin request and no CORS configuration needed on the FastAPI side at all, and `websocketUrl()` in `apiClient.ts` can build a relative `/ws/...` URL against the page's own origin and trust the proxy to route it correctly. The config's own comment notes it binds to `127.0.0.1` rather than `localhost` as the proxy target specifically because Node can resolve `localhost` to the IPv6 loopback address, which fails if the backend is only listening on IPv4. Beyond that, TypeScript's project references (`tsconfig.app.json` for the app code, `tsconfig.node.json` for Vite's own config file) exist mainly so the `@` path alias and compiler options can differ between "code that runs in the browser" and "code that runs in Node while building," and `npm run typecheck` runs both before every build; this is standard Vite-plus-TypeScript scaffolding and is not worth digging into further as a beginner.

## 7. Checklist for starting a new React project from scratch

1. **Pick a routing library and decide the layout-route pattern up front.** Classic `<Routes>`/`<Route>` or a data-router, decide before ten pages exist whether shared chrome (nav, sidebar, tabs) lives in nested layout routes with an `<Outlet/>`, so you never copy-paste a header into every page.

2. **Give network code exactly one entry point.** One thin module (`lib/apiClient.ts` here) is the only place `fetch()` is called, so auth headers, retries, and error-shape parsing exist in one file, not reinvented per request.

3. **Separate "what can I ask the server" from "how do I make a request."** Named, typed functions per backend resource in a `services/` layer that calls your API client, not `fetch()` from components, so request mechanics can change later without touching a single page.

4. **Model the wire contract with real types, colocated by resource.** TypeScript types for exactly what your backend sends and expects, one `models/` file per resource, so a renamed backend field is a compile error, not a silent runtime bug a user finds first.

5. **Group components by feature, and keep a separate feature-agnostic UI kit.** Decide early what is reusable because it knows nothing about your domain (buttons, inputs, tables) versus reusable because it solves one feature's problem, and fold them into different folders so a contributor can tell at a glance what is safe to reuse anywhere.

6. **Reach for a custom hook once loading or async logic repeats, not before.** The first page can call a service function inside a plain `useEffect`. The second page needing the same loading/error/refetch behavior is the signal to extract a hook like `useAsyncData`, solving cancellation and stale-data handling once.

7. **Put a dedicated store layer between "local state" and "the whole app."** A small state library only for values multiple unrelated components need, or that non-component code must read directly; everything else stays local `useState` rather than defaulting to a global store.

8. **Solve WebSocket auth with a short-lived ticket, not the access token in the URL.** Browsers cannot attach custom headers to a `WebSocket` handshake, so mint a one-time, quickly expiring ticket over an authenticated HTTP call right before opening the connection.

9. **Wrap authenticated binary resources in an object-URL fetch, never a bare `src` or `href`.** A plain `<img src>` or `<a href>` sends no Authorization header; fetch as a blob through your authenticated client, turn it into a `URL.createObjectURL()`, and revoke it when done.

10. **Configure your dev server's proxy before writing any fetch code.** Route `/api` (and `/ws`, for WebSockets) to your backend, so the browser only ever talks to one origin in development and CORS never comes up.

11. **Keep your true application root trivial.** A root that only wraps a router in your top-level providers means there is always exactly one obvious place to add the next app-wide concern.

12. **Decide folder boundaries by asking "what does NOT belong here," not just "what does."** Every folder needs a one-sentence responsibility and a clear misfit answer, written down before it fills up, because a boundary nobody can articulate erodes the first time someone is in a hurry.
