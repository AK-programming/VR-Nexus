/**
 * Tender Tools -- four analysis utilities on one tabbed page, styled to match
 * the DPL TenderFlow tools workspace layout.
 *
 * Layout (top to bottom):
 *  - Back link
 *  - Module shortcut cards (grid of 4 quick-nav buttons)
 *  - Tender info bar with status
 *  - Horizontal tab bar (navy active state)
 *  - Active tool panel with heading + action buttons
 *
 * Data is fetched once and shared across tabs, so switching is instant.
 */

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ROUTES, tenderDetailPath } from '@/constants/routes'
import { isInFlight, tenderTitle } from '@/models/tenders'
import {
  getTender,
  getReport,
  listRequirements,
  listMatches,
} from '@/services/tenderService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { TenderStatusPill } from '@/components/tender/TenderStatusPill'
import {
  ChevronLeftIcon,
  ClipboardCheckIcon,
  CalculatorIcon,
  ShieldAlertIcon,
  PackageCheckIcon,
} from '@/components/ui/icons'
import { ComplianceMatrix } from '@/components/tender/ComplianceMatrix'
import { EvaluationSimulator } from '@/components/tender/EvaluationSimulator'
import { RiskScanner } from '@/components/tender/RiskScanner'
import { SubmissionChecker } from '@/components/tender/SubmissionChecker'

type ToolTab = 'compliance' | 'evaluation' | 'risk' | 'submission'

const TABS: { value: ToolTab; label: string; icon: typeof ClipboardCheckIcon }[] = [
  { value: 'compliance', label: 'Compliance Matrix', icon: ClipboardCheckIcon },
  { value: 'evaluation', label: 'Evaluation Simulator', icon: CalculatorIcon },
  { value: 'risk', label: 'Risk Scanner', icon: ShieldAlertIcon },
  { value: 'submission', label: 'Submission Checker', icon: PackageCheckIcon },
]

/** Module shortcut cards at the top of the tools page. */
const MODULE_SHORTCUTS = [
  { to: ROUTES.tenderAnalysis, icon: '▤', label: 'Tender Analysis', sub: 'Pipeline overview' },
  { to: ROUTES.documents, icon: '◇', label: 'Evidence Library', sub: 'Reusable documents' },
  { to: ROUTES.settings, icon: '⚙', label: 'Settings', sub: 'Workspace config' },
  { to: ROUTES.home, icon: '⌂', label: 'Dashboard', sub: 'Overview and stats' },
] as const

/** Tool heading with title, description, and optional action buttons. */
function ToolHeading({
  title,
  description,
  actions,
}: {
  title: string
  description: string
  actions?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
      <div>
        <h2 className="font-display text-lg font-bold text-neutral-900">{title}</h2>
        <p className="mt-0.5 text-xs text-neutral-500">{description}</p>
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function TenderToolsPage() {
  const { tenderId = '' } = useParams()
  const [activeTab, setActiveTab] = useState<ToolTab>('compliance')

  const detail = useAsyncData(
    async (signal) => {
      const [tender, requirements, matches, report] = await Promise.all([
        getTender(tenderId, { signal }),
        listRequirements(tenderId, {}, { signal }),
        listMatches(tenderId, {}, { signal }),
        getReport(tenderId, { signal }),
      ])
      return { tender, requirements, matches, report }
    },
    [tenderId],
  )

  /* ---- Loading / error gates ---- */
  if (detail.status === 'loading' && detail.data === null) {
    return (
      <Panel title="Tender Tools" description="Loading the tender data.">
        <LoadingRows rows={5} label="Loading tender analysis" />
      </Panel>
    )
  }

  if (detail.status === 'error' && detail.data === null) {
    return (
      <Panel title="Tender Tools">
        <ErrorBlock
          title={detail.notFound ? 'This tender could not be found' : 'The tender could not be read'}
          message={
            detail.notFound
              ? 'It may have been removed, or the link is out of date.'
              : detail.error ?? 'The request did not complete.'
          }
          offline={detail.offline}
          onRetry={detail.notFound ? undefined : detail.refetch}
        />
        {detail.notFound ? (
          <div className="flex justify-center pb-8">
            <ActionButton variant="secondary" size="sm" to={ROUTES.tenderAnalysis}>
              Back to tenders
            </ActionButton>
          </div>
        ) : null}
      </Panel>
    )
  }

  const tender = detail.data!.tender
  const requirements = detail.data!.requirements
  const matches = detail.data!.matches
  const report = detail.data!.report

  /* Still analysing: the tools have nothing to work with yet. */
  if (isInFlight(tender.status) || tender.status === 'uploaded' || tender.status === 'failed') {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        <Link
          to={ROUTES.tenderAnalysis}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-600 transition-colors hover:text-neutral-900"
        >
          <ChevronLeftIcon className="size-4" />
          Back to tenders
        </Link>
        <Panel title={tenderTitle(tender)} action={<TenderStatusPill status={tender.status} />}>
          <AlertMessage tone="info" title="Tools are available after analysis">
            The tender tools require a completed analysis. Please wait until the pipeline
            reaches "Ready for review" before using these tools.
          </AlertMessage>
        </Panel>
      </div>
    )
  }

  const readinessPercent = report.coverage_percent != null ? Math.round(report.coverage_percent) : 0

  return (
    <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
      {/* Back link */}
      <Link
        to={tenderDetailPath(tenderId)}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-600 transition-colors hover:text-neutral-900"
      >
        <ChevronLeftIcon className="size-4" />
        Back to review
      </Link>

      {/* Module shortcuts grid */}
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {MODULE_SHORTCUTS.map((shortcut) => (
          <Link
            key={shortcut.to}
            to={shortcut.to}
            className="group grid grid-cols-[auto_1fr] grid-rows-[auto_auto] gap-x-2.5 rounded-xl border border-hairline bg-surface p-3 shadow-sm transition-colors hover:border-neutral-300"
          >
            <span className="row-span-2 flex size-8 items-center justify-center rounded-lg bg-brand-50 text-base text-brand-600">
              {shortcut.icon}
            </span>
            <span className="text-xs font-bold text-neutral-900">{shortcut.label}</span>
            <span className="text-[10px] text-neutral-500">{shortcut.sub}</span>
          </Link>
        ))}
      </div>

      {/* Tender info bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-hairline bg-surface px-4 py-3 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
            Working tender
          </span>
          <span className="text-sm font-semibold text-neutral-900">{tenderTitle(tender)}</span>
        </div>
        <div className="flex items-center gap-2">
          <TenderStatusPill status={tender.status} />
          <span className="rounded-lg bg-surface-muted px-2.5 py-1 text-xs font-bold text-neutral-600">
            {readinessPercent}% ready
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <nav className="flex gap-2 overflow-x-auto border-b border-hairline pb-3">
        {TABS.map((tab) => {
          const isActive = activeTab === tab.value
          return (
            <button
              key={tab.value}
              type="button"
              onClick={() => setActiveTab(tab.value)}
              className={[
                'flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-bold transition-colors duration-150',
                isActive
                  ? 'bg-ink-800 text-white shadow-sm'
                  : 'text-neutral-500 hover:bg-surface-muted hover:text-neutral-900',
              ].join(' ')}
            >
              {tab.label}
            </button>
          )
        })}
      </nav>

      {/* Active tool */}
      <div>
        {activeTab === 'compliance' ? (
          <>
            <ToolHeading
              title="RFP Compliance Matrix"
              description="Every requirement, clause, owner, evidence, deadline and status in one table."
            />
            <ComplianceMatrix
              tenderId={tenderId}
              requirements={requirements}
              matches={matches}
            />
          </>
        ) : activeTab === 'evaluation' ? (
          <>
            <ToolHeading
              title="Evaluation Score Simulator"
              description="Estimate the technical score and identify areas where marks may be lost."
            />
            <EvaluationSimulator
              tender={tender}
              report={report}
              requirements={requirements}
            />
          </>
        ) : activeTab === 'risk' ? (
          <>
            <ToolHeading
              title="Risk Scanner"
              description="Pattern-based detection of liability, SLA, payment, and other risk phrases."
            />
            <RiskScanner requirements={requirements} />
          </>
        ) : (
          <>
            <ToolHeading
              title="AI Submission Package Checker"
              description="Check forms, signatures, approvals and attachments before final submission."
            />
            <SubmissionChecker
              tenderId={tenderId}
              tender={tender}
              report={report}
              requirements={requirements}
              matches={matches}
            />
          </>
        )}
      </div>
    </div>
  )
}
