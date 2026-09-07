/**
 * The one place a route is declared.
 *
 * Guards are applied here rather than inside the pages, so the rule for a URL is
 * readable from the route table alone and a new page cannot forget to protect
 * itself. Imports are eager: these screens are small, and code-splitting them would
 * buy a loading state on the very first paint in exchange for bytes the user is
 * about to need anyway.
 *
 * Everything behind the sign-in wall hangs off one pathless layout route. That is
 * what puts `DashboardLayout` — sidebar, header, footer — around every signed-in page
 * without any page importing it, and it means the shell is mounted once and survives
 * navigation rather than being torn down and rebuilt on each link.
 *
 * Placeholder routes are registered on purpose rather than left out. Every sidebar item
 * points at a real path, every in-app link points at a registered one, and the catch-all
 * below sends unknown URLs to sign-in — so an unregistered path does not show a "not
 * found" page, it throws a signed-in user out of the app. Four of the five placeholders
 * are sidebar destinations; the fifth is the tender review workspace, which two built
 * pages already link to.
 *
 * Documents and Tender Analysis each nest a second layout route inside the first. Two
 * levels of shell is the point: the dashboard chrome is the same on every signed-in page,
 * and a section's heading and tabs are the same across its three screens, so each is
 * mounted once at the level it actually belongs to. Both sections then put their
 * single-item view — one document open for reading, one tender open for review — outside
 * those tabs, as an absolute-path sibling.
 */

import { Navigate, Route, Routes } from 'react-router-dom'
import { RedirectIfAuthenticated, RequireAuth } from '@/app/guards'
import { DOCUMENT_VIEWER_PATTERN, ROUTES, TENDER_DETAIL_PATTERN, TENDER_TOOLS_PATTERN } from '@/constants/routes'
import { DashboardLayout } from '@/Layout/DashboardLayout'
import { DocumentsLayout } from '@/Layout/DocumentsLayout'
import { TenderAnalysisLayout } from '@/Layout/TenderAnalysisLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { DocumentsOverviewPage } from '@/pages/DocumentsOverviewPage'
import { ForgotPasswordPage } from '@/pages/ForgotPasswordPage'
import { LoginPage } from '@/pages/LoginPage'
import { PdfViewerPage } from '@/pages/PdfViewerPage'
import { ProcessingPage } from '@/pages/ProcessingPage'
import { RegisterPage } from '@/pages/RegisterPage'
import { ResetPasswordPage } from '@/pages/ResetPasswordPage'
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

export function AppRouter() {
  return (
    <Routes>
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

      <Route
        element={
          <RequireAuth>
            <DashboardLayout />
          </RequireAuth>
        }
      >
        <Route path={ROUTES.home} element={<DashboardPage />} />

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
        <Route path={ROUTES.tenderAnalysis} element={<TenderAnalysisLayout />}>
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
            <TenderReviewPage />
          }
        />

        {/* The four tender tools (compliance matrix, evaluation simulator, risk
            scanner, submission checker) sit under the tender detail as a
            sibling, so the tools page can read the tender id from the URL and
            fetch the same data the review page does. */}
        <Route path={TENDER_TOOLS_PATTERN} element={<TenderToolsPage />} />

        {/*
          Documents is a section, so it gets a layout route of its own nested inside the
          dashboard shell: `DocumentsLayout` draws the heading and the segmented control
          once, and the three children below fill in under it. `index` rather than a
          second `/documents` path, so the parent owns the URL and the child cannot
          disagree with it.
        */}
        <Route path={ROUTES.documents} element={<DocumentsLayout />}>
          <Route index element={<DocumentsOverviewPage />} />
          <Route path="upload" element={<UploadDocumentsPage />} />
          <Route path="processing" element={<ProcessingPage />} />
        </Route>

        {/* The viewer is a sibling, not a fourth child: it is one document open for
            reading, and the section's tabs would offer to navigate away from it as if
            it were a peer of Library and Upload. It keeps the dashboard shell and gets
            a back link instead. */}
        <Route path={DOCUMENT_VIEWER_PATTERN} element={<PdfViewerPage />} />

        <Route
          path={ROUTES.assistant}
          element={
            <AiAssistantPage />
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
      </Route>

      {/* Unknown URLs go to sign-in, not home: home is guarded, so sending them
          there would bounce straight here anyway and burn a history entry. */}
      <Route path="*" element={<Navigate to={ROUTES.login} replace />} />
    </Routes>
  )
}
