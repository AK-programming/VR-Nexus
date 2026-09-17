/**
 * The one place a route is declared.
 *
 * Guards are applied here rather than inside the pages, so the rule for a URL is
 * readable from the route table alone and a new page cannot forget to protect
 * itself. Imports are eager: these screens are small, and code-splitting them would
 * buy a loading state on the very first paint in exchange for bytes the user is
 * about to need anyway.
 *
 * Everything behind the sign-in wall except the root hangs off one pathless layout
 * route. That is what puts `DashboardLayout` — sidebar, header, footer — around every
 * signed-in page without any page importing it, and it means the shell is mounted once
 * and survives navigation rather than being torn down and rebuilt on each link. `/`
 * itself is the one exception — see `HomeRoute` below, which splits it by auth state
 * instead of gating it with `RequireAuth` like everything else, so a signed-out visit
 * shows the marketing landing page rather than bouncing straight to `/login`.
 *
 * Placeholder routes are registered on purpose rather than left out. Every sidebar item
 * points at a real path, every in-app link points at a registered one, and the catch-all
 * below sends unknown URLs to `/` — so an unregistered path does not show a "not found"
 * page, it lands on `HomeRoute`, which resolves to the landing page or the dashboard
 * depending on who's asking. Four of the five placeholders are sidebar destinations;
 * the fifth is the tender review workspace, which two built pages already link to.
 *
 * Documents and Tender Analysis each nest a second layout route inside the first. Two
 * levels of shell is the point: the dashboard chrome is the same on every signed-in page,
 * and a section's heading and tabs are the same across its three screens, so each is
 * mounted once at the level it actually belongs to. Both sections then put their
 * single-item view — one document open for reading, one tender open for review — outside
 * those tabs, as an absolute-path sibling.
 */

import { Navigate, Route, Routes } from 'react-router-dom'
import { RedirectIfAuthenticated, RequireAdmin, RequireAuth, RequireFeature } from '@/app/guards'
import { DOCUMENT_VIEWER_PATTERN, ROUTES, TENDER_DETAIL_PATTERN, TENDER_TOOLS_PATTERN } from '@/constants/routes'
import { DashboardLayout } from '@/Layout/DashboardLayout'
import { DocumentsLayout } from '@/Layout/DocumentsLayout'
import { TenderAnalysisLayout } from '@/Layout/TenderAnalysisLayout'
import { AdminSettingsPage } from '@/pages/AdminSettingsPage'
import { AdminUsersPage } from '@/pages/AdminUsersPage'
import { ApiUsagePage } from '@/pages/ApiUsagePage'
import { DashboardPage } from '@/pages/DashboardPage'
import { DocumentsOverviewPage } from '@/pages/DocumentsOverviewPage'
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage'
import { LandingPage } from '@/pages/LandingPage'
import { LoginPage } from '@/pages/LoginPage'
import { PdfViewerPage } from '@/pages/PdfViewerPage'
import { ProcessingPage } from '@/pages/ProcessingPage'
import { RegisterPage } from '@/pages/RegisterPage'
import { ResetPasswordPage } from '@/pages/ResetPasswordPage'
import { VerifyEmailPage } from '@/pages/VerifyEmailPage'
import { TenderOverviewPage } from '@/pages/TenderOverviewPage'
import { TenderProcessingPage } from '@/pages/TenderProcessingPage'
import { TenderReviewPage } from '@/pages/TenderReviewPage'
import { TenderToolsPage } from '@/pages/TenderToolsPage'
import { AiAssistantPage } from '@/pages/AiAssistantPage'
import { ActivityPage } from '@/pages/ActivityPage'
import { SettingsPage } from '@/pages/SettingsPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { UploadDocumentsPage } from '@/pages/UploadDocumentsPage'
import { UploadTenderPage } from '@/pages/UploadTenderPage'
import { selectIsAuthenticated, useAuthStore } from '@/store/authStore'

/**
 * `/` itself, split by auth state rather than gated by `RequireAuth` like
 * everything else under the dashboard shell.
 *
 * Every other authenticated route still bounces a signed-out visit to
 * `/login` — that is unchanged, and is the right call for a deep link
 * someone was sent (they should sign in and land back where they meant to
 * go). The root is different: a signed-out visit to `/` is the product's
 * front door, so it shows the marketing page instead of a bare login
 * redirect. `isAuthenticated` here is the same optimistic read `RequireAuth`
 * uses — a restored session counts immediately, before its background
 * validation resolves — so this never disagrees with the rest of the app
 * about who is signed in.
 */
function HomeRoute() {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)

  if (!isAuthenticated) {
    return <LandingPage />
  }

  return (
    <DashboardLayout>
      <DashboardPage />
    </DashboardLayout>
  )
}

export function AppRouter() {
  return (
    <Routes>
      <Route path={ROUTES.home} element={<HomeRoute />} />

      <Route
        path={ROUTES.login}
        element={
          <RedirectIfAuthenticated>
            <LoginPage />
          </RedirectIfAuthenticated>
        }
      />
      <Route
        path={ROUTES.register}
        element={
          <RedirectIfAuthenticated>
            <RegisterPage />
          </RedirectIfAuthenticated>
        }
      />

      {/* Not gated by RedirectIfAuthenticated like the two routes above: a
          password reset link in an email can land on a browser where an
          older session is still signed in, and there is no reason to bounce
          that away from the one screen that can act on it. */}
      <Route path={ROUTES.forgotPassword} element={<ForgotPasswordPage />} />
      <Route path={ROUTES.resetPassword} element={<ResetPasswordPage />} />
      {/* Same reasoning as the two routes above: reached from a link in an
          email, not from inside the app, so it is not gated by
          RedirectIfAuthenticated or RequireAuth either. */}
      <Route path={ROUTES.verifyEmail} element={<VerifyEmailPage />} />

      <Route
        element={
          <RequireAuth>
            <DashboardLayout />
          </RequireAuth>
        }
      >
        {/*
          Tender Analysis is a section, so — exactly as Documents does below — it gets a
          layout route of its own nested inside the dashboard shell, with `index` rather
          than a second `/tender-analysis` path so the parent owns the URL and the child
          cannot disagree with it.

          Declaration order does not decide which child matches: React Router ranks by
          specificity, so the static `upload` and `processing` segments outrank the
          `:tenderId` sibling underneath, and /tender-analysis/upload can never be read
          as a tender whose id happens to be "upload".
        */}
        <Route
          path={ROUTES.tenderAnalysis}
          element={
            <RequireFeature feature="tender_analysis">
              <TenderAnalysisLayout />
            </RequireFeature>
          }
        >
          <Route index element={<TenderOverviewPage />} />
          <Route path="upload" element={<UploadTenderPage />} />
          <Route path="processing" element={<TenderProcessingPage />} />
        </Route>

        {/* One tender open for review, so a sibling rather than a fourth tab, for the
            reason the PDF viewer is one: the section's tabs would offer to navigate
            away from it as if it were a peer of Overview and Upload.

            The screen itself is not designed yet, so it renders the placeholder — but
            the route has to exist either way. TenderOverviewPage and
            TenderProcessingPage both already link here via tenderDetailPath(), and an
            unregistered target does not 404, it falls to the catch-all and signs the
            user out. */}
        <Route
          path={TENDER_DETAIL_PATTERN}
          element={
            <RequireFeature feature="tender_analysis">
              <TenderReviewPage />
            </RequireFeature>
          }
        />

        {/* The four tender tools (compliance matrix, evaluation simulator, risk
            scanner, submission checker) sit under the tender detail as a
            sibling, so the tools page can read the tender id from the URL and
            fetch the same data the review page does.

            Client follow-up request: Tender Tools only makes sense on top of
            Tender Analysis, so this requires BOTH grants rather than either -
            an account with tender_tools alone has nothing here to open. */}
        <Route
          path={TENDER_TOOLS_PATTERN}
          element={
            <RequireFeature feature={['tender_analysis', 'tender_tools']} requireAll>
              <TenderToolsPage />
            </RequireFeature>
          }
        />

        {/*
          Documents is a section, so it gets a layout route of its own nested inside the
          dashboard shell: `DocumentsLayout` draws the heading and the segmented control
          once, and the three children below fill in under it. `index` rather than a
          second `/documents` path, so the parent owns the URL and the child cannot
          disagree with it.
        */}
        {/* Client follow-up request: `documents` and `documents_upload` are two
            separate grants (view/manage the library vs. contribute to it), so
            the section itself only needs either one, while the index (Library)
            route below requires the full `documents` grant specifically. */}
        <Route
          path={ROUTES.documents}
          element={
            <RequireFeature feature={['documents', 'documents_upload']}>
              <DocumentsLayout />
            </RequireFeature>
          }
        >
          <Route
            index
            element={
              <RequireFeature feature="documents">
                <DocumentsOverviewPage />
              </RequireFeature>
            }
          />
          <Route path="upload" element={<UploadDocumentsPage />} />
          <Route path="processing" element={<ProcessingPage />} />
        </Route>

        {/* The viewer is a sibling, not a fourth child: it is one document open for
            reading, and the section's tabs would offer to navigate away from it as if
            it were a peer of Library and Upload. It keeps the dashboard shell and gets
            a back link instead. Reading a document needs the full `documents` grant,
            not just upload rights. */}
        <Route
          path={DOCUMENT_VIEWER_PATTERN}
          element={
            <RequireFeature feature="documents">
              <PdfViewerPage />
            </RequireFeature>
          }
        />

        <Route
          path={ROUTES.assistant}
          element={
            <RequireFeature feature="ai_assistant">
              <AiAssistantPage />
            </RequireFeature>
          }
        />
        <Route
          path={ROUTES.activity}
          element={
            <ActivityPage />
          }
        />
        <Route
          path={ROUTES.settings}
          element={
            <SettingsPage />
          }
        />
        <Route
          path={ROUTES.profile}
          element={
            <ProfilePage />
          }
        />

        {/* Admin-only: the Users list and their per-section access grants.
            Nested inside RequireAuth's shell so a signed-out visit still
            lands on /login (readReturnPath then sends them straight back
            here), and wrapped again in RequireAdmin so a signed-in
            non-admin bounces to the dashboard instead of seeing the page
            flash before its data request 403s. */}
        <Route
          path={ROUTES.adminUsers}
          element={
            <RequireAdmin>
              <AdminUsersPage />
            </RequireAdmin>
          }
        />

        {/* Admin-only: the shared Anthropic API key and per-model pricing
            table. Same RequireAdmin wrapping as Users above, and same
            reasoning — the backend's /api/admin/settings/* routes are the
            real guard, this just keeps a non-admin from seeing the page
            flash before that 403s. */}
        <Route
          path={ROUTES.adminSettings}
          element={
            <RequireAdmin>
              <AdminSettingsPage />
            </RequireAdmin>
          }
        />

        {/* Anthropic API token usage and estimated cost. Open to every
            signed-in account, unlike Users above — no RequireAdmin here —
            because the page is scoped server-side to the caller: an admin
            sees everyone's usage, anyone else sees only their own (see
            backend/app/api/routes/usage.py and ApiUsagePage's own
            comment). RequireAuth's shell above is still enough to keep a
            signed-out visit bouncing to /login. */}
        <Route path={ROUTES.apiUsage} element={<ApiUsagePage />} />
      </Route>

      {/* Unknown URLs go to `/`, not straight to sign-in: `HomeRoute` above
          already splits that by auth state, so a signed-out visitor gets
          the landing page instead of a bare login form, and a signed-in
          one gets the dashboard - the same place a stray link inside the
          app would have sent them anyway. */}
      <Route path="*" element={<Navigate to={ROUTES.home} replace />} />
    </Routes>
  )
}
