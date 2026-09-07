/**
 * The tender review workspace — one tender opened for clause-by-clause review.
 *
 * This is the screen the whole pipeline builds toward and the one the router used
 * to fill with a placeholder. It is a sibling of the section's tabs, not a fourth
 * tab (see the routing note), so it carries the dashboard shell and a back link
 * rather than the Overview/Upload/Processing segmented control.
 *
 * It reads four things at once — the tender, its requirements, its evidence
 * matches, and the computed report — because they are one coherent picture and a
 * staggered load would draw the summary before the rows it summarises. Review
 * actions (accept / reject / reassign a match, then finalize) mutate the server
 * and refetch, so the coverage number and the row chips are always the server's
 * truth rather than an optimistic guess that can drift from the marks total.
 *
 * The human checkpoint is the whole point of this page: the AI proposes matches,
 * a person confirms them here, and only then does Finalize lock the output folder.
 * Finalize is deliberately gated on the pipeline having reached READY_FOR_REVIEW —
 * exactly the backend's own precondition — so the button cannot get ahead of the
 * analysis.
 */

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ROUTES, tenderToolsPath } from '@/constants/routes'
import {
  EVALUATION_IMPACT_LABELS,
  isInFlight,
  tenderTitle,
} from '@/models/tenders'
import type { EvidenceMatch, MatchReviewAction } from '@/models/tenders'
import {
  finalizeTender,
  getReport,
  getTender,
  listMatches,
  listRequirements,
  reviewMatch,
  fetchTenderOutputObjectUrl,
  releaseObjectUrl,
} from '@/services/tenderService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { errorMessage } from '@/lib/apiClient'
import { formatCount, formatRelativeTime } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { TenderStatusPill } from '@/components/tender/TenderStatusPill'
import {
  RequirementReviewCard,
  requirementCoverage,
  isNarrativeBoilerplate,
} from '@/components/tender/RequirementReviewCard'
import type { CoverageState } from '@/components/tender/RequirementReviewCard'
import { ReassignDialog } from '@/components/tender/ReassignDialog'
import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ClipboardCheckIcon,
  DownloadIcon,
  ShieldCheckIcon,
} from '@/components/ui/icons'

type ReviewFilter = 'all' | 'review' | 'missing'

const FILTERS: { value: ReviewFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'review', label: 'Needs review' },
  { value: 'missing', label: 'Missing' },
]

/** A labelled tile for the summary strip — the product's card surface, kept small. */
function StatTile({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: string
  hint?: string
  tone?: 'neutral' | 'emerald' | 'amber' | 'rose'
}) {
  // dark: overrides here because these render as bare status-coloured text on
  // a `bg-surface` card, with no matching coloured background of their own to
  // carry contrast the way a chip does - see the `@custom-variant dark`
  // comment in index.css.
  const valueTone: Record<typeof tone, string> = {
    neutral: 'text-neutral-900',
    emerald: 'text-emerald-700 dark:text-emerald-300',
    amber: 'text-amber-700 dark:text-amber-300',
    rose: 'text-rose-700 dark:text-rose-300',
  }
  return (
    <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
      <p className="text-xs font-medium text-neutral-500">{label}</p>
      <p className={['mt-1 font-display text-2xl font-semibold tabular-nums', valueTone[tone]].join(' ')}>
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-xs text-neutral-500">{hint}</p> : null}
    </div>
  )
}

export function TenderReviewPage() {
  const { tenderId = '' } = useParams()

  const [busyMatchId, setBusyMatchId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [reassignMatch, setReassignMatch] = useState<EvidenceMatch | null>(null)
  const [confirmFinalize, setConfirmFinalize] = useState(false)
  const [finalizing, setFinalizing] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [filter, setFilter] = useState<ReviewFilter>('all')
  const [showNarrative, setShowNarrative] = useState(false)

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

  /* Matches grouped by the requirement they answer, so each card gets only its own. */
  const matchesByRequirement = useMemo(() => {
    const map = new Map<string, EvidenceMatch[]>()
    for (const match of detail.data?.matches ?? []) {
      const list = map.get(match.requirement_id)
      if (list) list.push(match)
      else map.set(match.requirement_id, [match])
    }
    return map
  }, [detail.data?.matches])

  const requirements = detail.data?.requirements ?? []

  /* Boilerplate front matter (disclaimers, executive-summary preamble) split out
     of the working list — it was never a compliance obligation, so it doesn't
     belong in "160 requirements" the way a real clause does. Kept out of
     visibleRequirements below by construction; shown collapsed, with a toggle,
     rather than deleted or hidden with no trace. */
  const narrativeRequirements = useMemo(
    () => requirements.filter(isNarrativeBoilerplate),
    [requirements],
  )
  const actionableRequirements = useMemo(
    () => requirements.filter((req) => !isNarrativeBoilerplate(req)),
    [requirements],
  )
  const narrativePercent =
    requirements.length > 0
      ? Math.round((narrativeRequirements.length / requirements.length) * 100)
      : 0

  const visibleRequirements = useMemo(() => {
    if (filter === 'all') return actionableRequirements
    return actionableRequirements.filter((req) => {
      const coverage: CoverageState = requirementCoverage(
        req,
        matchesByRequirement.get(req.id) ?? [],
      )
      if (filter === 'missing') return coverage === 'missing'
      // 'review' — anything a person still has to look at.
      return coverage === 'review' || req.needs_manual_review
    })
  }, [filter, actionableRequirements, matchesByRequirement])

  async function handleReview(
    matchId: string,
    action: MatchReviewAction,
    documentId?: string,
  ) {
    setBusyMatchId(matchId)
    setActionError(null)
    try {
      await reviewMatch(tenderId, matchId, { action, document_id: documentId })
      detail.refetch()
      setReassignMatch(null)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setBusyMatchId(null)
    }
  }

  async function handleFinalize() {
    setFinalizing(true)
    setActionError(null)
    try {
      await finalizeTender(tenderId)
      detail.refetch()
      setConfirmFinalize(false)
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      setFinalizing(false)
    }
  }

  async function handleDownload() {
    setDownloading(true)
    setActionError(null)
    let url: string | null = null
    try {
      url = await fetchTenderOutputObjectUrl(tenderId)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${tender ? tenderTitle(tender) : 'tender'}-analysis.zip`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (error) {
      setActionError(errorMessage(error))
    } finally {
      releaseObjectUrl(url)
      setDownloading(false)
    }
  }

  /* ---- Loading / error / not-found gates ---- */
  if (detail.status === 'loading' && detail.data === null) {
    return (
      <Panel title="Tender review" description="Opening the tender.">
        <LoadingRows rows={5} label="Loading the tender analysis" />
      </Panel>
    )
  }

  if (detail.status === 'error' && detail.data === null) {
    return (
      <Panel title="Tender review">
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
  const report = detail.data!.report
  const finalized = tender.status === 'finalized'
  const ready = tender.status === 'ready_for_review'

  const backLink = (
    <Link
      to={ROUTES.tenderAnalysis}
      className="inline-flex items-center gap-1.5 text-sm font-medium text-neutral-600 transition-colors hover:text-neutral-900"
    >
      <ChevronLeftIcon className="size-4" />
      Back to tenders
    </Link>
  )

  /* Still analysing (or failed): the workspace has nothing to review yet. */
  if (isInFlight(tender.status) || tender.status === 'uploaded' || tender.status === 'failed') {
    const failed = tender.status === 'failed'
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        {backLink}
        <Panel title={tenderTitle(tender)} action={<TenderStatusPill status={tender.status} />}>
          {failed ? (
            <AlertMessage tone="warning" title="This tender was not analysed">
              {tender.progress_message ||
                'The pipeline stopped before the analysis finished. Check that the source PDF is readable, or upload the tender again.'}
            </AlertMessage>
          ) : (
            <AlertMessage tone="info" title="Analysis in progress">
              VR-Nexus is still reading this tender. This page opens for review once the pipeline
              reaches “Ready for review”.
            </AlertMessage>
          )}
          <div className="mt-4">
            <ActionButton
              variant="secondary"
              size="sm"
              to={`${ROUTES.tenderProcessing}?tender=${tender.id}`}
            >
              {failed ? 'Open the pipeline' : 'Watch live progress'}
            </ActionButton>
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-[100rem] flex-col gap-4">
      {backLink}

      {/* Header */}
      <div className="flex flex-col gap-4 rounded-2xl border border-hairline bg-surface p-5 shadow-sm sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900">
              {tenderTitle(tender)}
            </h1>
            <TenderStatusPill status={tender.status} />
          </div>
          <p className="mt-1 text-sm text-neutral-500">
            {[
              tender.reference_id,
              tender.issuing_authority,
              tender.sector,
              tender.updated_at ? `Updated ${formatRelativeTime(tender.updated_at)}` : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <ActionButton
            variant="secondary"
            size="md"
            leadingIcon={<ClipboardCheckIcon />}
            to={tenderToolsPath(tenderId)}
          >
            Tender Tools
          </ActionButton>
          {tender.has_output ? (
            <ActionButton
              variant="secondary"
              size="md"
              leadingIcon={<DownloadIcon />}
              disabled={downloading}
              onClick={handleDownload}
            >
              {downloading ? 'Preparing…' : 'Download output'}
            </ActionButton>
          ) : null}
          {ready ? (
            <ActionButton
              variant="primary"
              size="md"
              leadingIcon={<ShieldCheckIcon />}
              onClick={() => setConfirmFinalize(true)}
            >
              Finalize tender
            </ActionButton>
          ) : null}
        </div>
      </div>

      {finalized ? (
        <AlertMessage tone="success" title="This tender is finalized">
          The output folder was assembled from the reviewed matches
          {tender.finalized_at ? ` ${formatRelativeTime(tender.finalized_at)}` : ''}. Re-finalize
          after any further changes to rebuild it.
        </AlertMessage>
      ) : null}

      {actionError ? (
        <AlertMessage tone="error" title="That action did not complete">
          {actionError}
        </AlertMessage>
      ) : null}

      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="Requirements"
          value={formatCount(report.requirements_total)}
          hint={`${report.mandatory_count} mandatory`}
        />
        <StatTile
          label="Coverage"
          value={`${Math.round(report.coverage_percent)}%`}
          hint={`${report.marks_captured} of ${report.marks_available} marks`}
          tone={report.coverage_percent >= 80 ? 'emerald' : report.coverage_percent >= 50 ? 'amber' : 'rose'}
        />
        <StatTile
          label="Needs review"
          value={formatCount(report.pending_matches)}
          hint="pending matches"
          tone={report.pending_matches > 0 ? 'amber' : 'neutral'}
        />
        <StatTile
          label="Unmatched"
          value={formatCount(report.requirements_without_evidence)}
          hint="no evidence yet"
          tone={report.requirements_without_evidence > 0 ? 'rose' : 'emerald'}
        />
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
        {/* Requirements + review */}
        <div className="min-w-0 flex-1">
          <Panel
            title="Requirements & evidence"
            description={
              narrativeRequirements.length > 0
                ? `${formatCount(actionableRequirements.length)} compliance requirements - expand a row to review its evidence. ${formatCount(narrativeRequirements.length)} more (${narrativePercent}%) are disclaimer/summary text, filtered below.`
                : `${formatCount(requirements.length)} extracted - expand a row to review its evidence.`
            }
            action={
              <div className="inline-flex items-center gap-1 rounded-xl border border-hairline bg-surface-muted p-1">
                {FILTERS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setFilter(option.value)}
                    aria-pressed={filter === option.value}
                    className={[
                      'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150',
                      filter === option.value
                        ? 'bg-surface text-neutral-900 shadow-sm'
                        : 'text-neutral-600 hover:text-neutral-900',
                    ].join(' ')}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            }
            flush
          >
            {filter === 'all' && narrativeRequirements.length > 0 ? (
              <div className="border-b border-hairline bg-surface-muted/60 px-5 py-3">
                <button
                  type="button"
                  onClick={() => setShowNarrative((v) => !v)}
                  aria-expanded={showNarrative}
                  className="flex w-full items-center justify-between gap-3 text-left"
                >
                  <span className="text-xs text-neutral-600">
                    <strong className="font-semibold text-neutral-900">
                      {formatCount(narrativeRequirements.length)}
                    </strong>{' '}
                    disclaimer / executive-summary statement
                    {narrativeRequirements.length === 1 ? '' : 's'} — {narrativePercent}% of
                    extracted content, not counted as compliance requirements.
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-brand-600">
                    {showNarrative ? 'Hide' : 'Show'}
                    <ChevronDownIcon
                      className={[
                        'size-3.5 transition-transform duration-150',
                        showNarrative ? 'rotate-180' : '',
                      ].join(' ')}
                    />
                  </span>
                </button>
                {showNarrative ? (
                  <div className="mt-3 flex flex-col divide-y divide-hairline rounded-xl border border-hairline bg-surface">
                    {narrativeRequirements.map((req) => (
                      <div key={req.id} className="px-3.5 py-2.5 text-xs text-neutral-600">
                        <span className="text-neutral-800">{req.description}</span>
                        {req.section_name ? (
                          <span className="ml-1.5 text-neutral-400">· {req.section_name}</span>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            {visibleRequirements.length === 0 ? (
              <p className="px-5 py-12 text-center text-sm text-neutral-500">
                {requirements.length === 0
                  ? 'No requirements were extracted from this tender.'
                  : narrativeRequirements.length > 0 && actionableRequirements.length === 0
                    ? 'Every extracted row was disclaimer/summary text — see above.'
                    : 'Nothing matches this filter.'}
              </p>
            ) : (
              <div className="flex flex-col divide-y divide-hairline">
                {visibleRequirements.map((req) => {
                  const originalIndex = requirements.indexOf(req)
                  return (
                    <RequirementReviewCard
                      key={req.id}
                      index={originalIndex + 1}
                      requirement={req}
                      matches={matchesByRequirement.get(req.id) ?? []}
                      locked={finalized}
                      busyMatchId={busyMatchId}
                      onReview={(matchId, action) => handleReview(matchId, action)}
                      onReassign={(match) => setReassignMatch(match)}
                    />
                  )
                })}
              </div>
            )}
          </Panel>
        </div>

        {/* Coverage by evaluation impact */}
        <div className="w-full xl:max-w-sm">
          <Panel title="Coverage by evaluation" description="Marks captured against marks available.">
            {report.by_evaluation_impact.length === 0 ? (
              <p className="text-sm text-neutral-500">
                No scored requirements were found in this tender.
              </p>
            ) : (
              <ul className="flex flex-col gap-4">
                {report.by_evaluation_impact.map((row) => {
                  const label =
                    EVALUATION_IMPACT_LABELS[
                      row.impact as keyof typeof EVALUATION_IMPACT_LABELS
                    ] ?? 'Unspecified'
                  const pct =
                    row.marks_available > 0
                      ? Math.round((row.marks_captured / row.marks_available) * 100)
                      : 0
                  return (
                    <li key={row.impact}>
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="text-sm font-medium text-neutral-800">{label}</span>
                        <span className="text-xs text-neutral-500 tabular-nums">
                          {row.marks_captured} / {row.marks_available} marks
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-neutral-200">
                        <div
                          className="h-full rounded-full bg-brand-500"
                          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                        />
                      </div>
                      <p className="mt-1 text-xs text-neutral-500">
                        {formatCount(row.requirement_count)}{' '}
                        {row.requirement_count === 1 ? 'requirement' : 'requirements'}
                      </p>
                    </li>
                  )
                })}
              </ul>
            )}

            {ready ? (
              <div className="mt-5 border-t border-hairline pt-4">
                <p className="text-xs leading-relaxed text-neutral-500">
                  When the matches look right, finalize to lock the analysis and assemble the
                  output folder from the accepted evidence.
                </p>
                <ActionButton
                  variant="primary"
                  size="sm"
                  leadingIcon={<ShieldCheckIcon />}
                  className="mt-3"
                  onClick={() => setConfirmFinalize(true)}
                >
                  Finalize tender
                </ActionButton>
              </div>
            ) : null}
          </Panel>
        </div>
      </div>

      <ReassignDialog
        open={reassignMatch !== null}
        requirementLabel={reassignMatch?.requirement_description ?? ''}
        currentDocumentId={reassignMatch?.document_id ?? null}
        busy={busyMatchId !== null && busyMatchId === reassignMatch?.id}
        onCancel={() => setReassignMatch(null)}
        onSelect={(documentId) => {
          if (reassignMatch) handleReview(reassignMatch.id, 'reassign', documentId)
        }}
      />

      <ConfirmDialog
        open={confirmFinalize}
        title="Finalize this tender?"
        description="This rebuilds the output folder from the currently accepted matches and locks the analysis. You can finalize again later if you change a match."
        confirmLabel={finalizing ? 'Finalizing…' : 'Finalize tender'}
        onConfirm={handleFinalize}
        onCancel={() => setConfirmFinalize(false)}
      />
    </div>
  )
}
