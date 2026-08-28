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
 * The five placeholder routes are registered on purpose. Every sidebar item points at
 * a real path, and the catch-all below sends unknown URLs to sign-in, so an
 * unregistered nav item would throw a signed-in user out of the app.
 *
 * Documents nests a second layout route inside the first. Two levels of shell is the
 * point: the dashboard chrome is the same on every signed-in page, and the Documents
 * heading and tabs are the same across that section's three screens, so each is mounted
 * once at the level it actually belongs to.
 */

import { Navigate, Route, Routes } from 'react-router-dom'
import { RedirectIfAuthenticated, RequireAuth } from '@/app/guards'
import { DOCUMENT_VIEWER_PATTERN, ROUTES } from '@/constants/routes'
import { DashboardLayout } from '@/Layout/DashboardLayout'
import { DocumentsLayout } from '@/Layout/DocumentsLayout'
import { DashboardPage } from '@/pages/DashboardPage'
import { DocumentsOverviewPage } from '@/pages/DocumentsOverviewPage'
import { LoginPage } from '@/pages/LoginPage'
import { PdfViewerPage } from '@/pages/PdfViewerPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'
import { ProcessingPage } from '@/pages/ProcessingPage'
import { RegisterPage } from '@/pages/RegisterPage'
import { UploadDocumentsPage } from '@/pages/UploadDocumentsPage'

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

      <Route
        element={
          <RequireAuth>
            <DashboardLayout />
          </RequireAuth>
        }
      >
        <Route path={ROUTES.home} element={<DashboardPage />} />

        <Route
          path={ROUTES.tenderAnalysis}
          element={
            <PlaceholderPage
              title="Tender Analysis"
              description="The analysis workspace is next on the roadmap. It will open a tender clause by clause, with the compliance checks alongside it."
            />
          }
        />
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
            <PlaceholderPage
              title="AI Assistant"
              description="The conversation view is not built yet. Your question came through, and it will be waiting when this page arrives."
            />
          }
        />
        <Route
          path={ROUTES.activity}
          element={
            <PlaceholderPage
              title="Activity"
              description="The full history of uploads, analyses and queries will live here. The dashboard shows the last few."
            />
          }
        />
        <Route
          path={ROUTES.settings}
          element={
            <PlaceholderPage
              title="Settings"
              description="Workspace, storage and notification preferences are on their way."
            />
          }
        />
        <Route
          path={ROUTES.profile}
          element={
            <PlaceholderPage
              title="Your profile"
              description="Editing your name, phone number and company is coming. Signing out is in the account menu at the top right."
            />
          }
        />
      </Route>

      {/* Unknown URLs go to sign-in, not home: home is guarded, so sending them
          there would bounce straight here anyway and burn a history entry. */}
      <Route path="*" element={<Navigate to={ROUTES.login} replace />} />
    </Routes>
  )
}
