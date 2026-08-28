/**
 * The shell the three Tender Analysis screens share.
 *
 * A nested route layout rather than a component each page renders, for the reason
 * `DocumentsLayout` and `DashboardLayout` are: mounted once, it survives
 * navigation between the tabs, so moving from Overview to Upload does not tear
 * down and rebuild the heading and the segmented control. It also means the
 * section owns exactly one `h1` — the pages below contribute panels with `h2`
 * headings, which keeps the document outline correct without any page needing to
 * know what level it sits at.
 *
 * The detail/review workspace is deliberately *not* a child of this route. It is
 * one tender opened for review, not a fourth section, and giving it these tabs
 * would suggest you can tab away and come back to the same place. It gets a back
 * link instead — exactly as the PDF viewer sits outside the documents tabs.
 */

import { NavLink, Outlet } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'

const TABS = [
  /* `end` only on the index tab: without it, /tender-analysis/upload would light
     Overview up as well, because a NavLink matches path prefixes by default. */
  { to: ROUTES.tenderAnalysis, label: 'Overview', end: true },
  { to: ROUTES.tenderUpload, label: 'Upload', end: false },
  { to: ROUTES.tenderProcessing, label: 'Processing', end: false },
]

export function TenderAnalysisLayout() {
  return (
    <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            Tender Analysis
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Upload a tender and VR-Nexus reads it clause by clause — extracting requirements,
            matching your evidence, and scoring coverage.
          </p>
        </div>

        {/*
          A segmented control, not a row of underlined tabs. These are three real
          URLs and each one is a link, so the browser's own affordances — middle
          click, copy link, back — all work; an ARIA tablist would take them over
          and break every one of them. `aria-current="page"` comes from NavLink and
          is what announces the active one.
        */}
        <nav aria-label="Tender analysis sections" className="shrink-0">
          <ul className="inline-flex items-center gap-1 rounded-xl border border-hairline bg-surface-muted p-1">
            {TABS.map((tab) => (
              <li key={tab.to}>
                <NavLink
                  to={tab.to}
                  end={tab.end}
                  className={({ isActive }) =>
                    [
                      'block rounded-lg px-3.5 py-2 text-sm font-medium transition-colors duration-150',
                      isActive
                        ? 'bg-surface text-neutral-900 shadow-sm'
                        : 'text-neutral-600 hover:text-neutral-900',
                    ].join(' ')
                  }
                >
                  {tab.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>

      <Outlet />
    </div>
  )
}
