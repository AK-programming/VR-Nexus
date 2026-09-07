/**
 * Submission Readiness Checker -- DPL-style two-column grid layout.
 * Left column: manual checkbox list with green accent.
 * Right column: AI-driven automated findings with pass/fail icon badges.
 */

import { useCallback, useMemo, useState } from 'react'
import type { Requirement, EvidenceMatch, TenderDetail, TenderReport } from '@/models/tenders'
import { CheckCircleIcon, XCircleIcon } from '@/components/ui/icons'

type CheckStatus = 'pass' | 'fail' | 'warning'

type AutoCheck = {
  id: string
  label: string
  status: CheckStatus
  detail: string
}

type ManualItem = {
  id: string
  label: string
}

const MANUAL_ITEMS: ManualItem[] = [
  { id: 'forms_signed', label: 'All required forms signed' },
  { id: 'bid_security', label: 'Bid security / earnest money attached' },
  { id: 'page_numbered', label: 'Pages numbered and indexed' },
  { id: 'copies_prepared', label: 'Correct number of copies prepared' },
  { id: 'envelope_labelled', label: 'Envelopes labelled correctly' },
  { id: 'power_of_attorney', label: 'Power of attorney included' },
  { id: 'addenda_acknowledged', label: 'All addenda acknowledged' },
  { id: 'pricing_checked', label: 'Pricing schedule reviewed' },
]

function loadChecked(tenderId: string): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(`vrnexus.submission.${tenderId}`)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveChecked(tenderId: string, data: Record<string, boolean>) {
  try {
    localStorage.setItem(`vrnexus.submission.${tenderId}`, JSON.stringify(data))
  } catch { /* quota */ }
}

type Props = {
  tenderId: string
  tender: TenderDetail
  report: TenderReport
  requirements: Requirement[]
  matches: EvidenceMatch[]
}

export function SubmissionChecker({ tenderId, tender, report, requirements, matches }: Props) {
  const [checked, setChecked] = useState<Record<string, boolean>>(() => loadChecked(tenderId))

  const toggleItem = useCallback(
    (id: string) => {
      setChecked((prev) => {
        const next = { ...prev, [id]: !prev[id] }
        saveChecked(tenderId, next)
        return next
      })
    },
    [tenderId],
  )

  // Automated checks
  const autoChecks: AutoCheck[] = useMemo(() => {
    const checks: AutoCheck[] = []

    // 1. Coverage
    const coveragePct = report.coverage_percent
    checks.push({
      id: 'coverage',
      label: 'Evidence coverage',
      status: coveragePct >= 90 ? 'pass' : coveragePct >= 70 ? 'warning' : 'fail',
      detail: `${Math.round(coveragePct)}% coverage (${report.requirements_with_evidence} of ${report.requirements_total})`,
    })

    // 2. Mandatory requirements
    const mandatoryMissing = requirements.filter(
      (r) => r.is_mandatory && r.match_count === 0,
    ).length
    checks.push({
      id: 'mandatory',
      label: 'Mandatory requirements',
      status: mandatoryMissing === 0 ? 'pass' : 'fail',
      detail:
        mandatoryMissing === 0
          ? `All ${report.mandatory_count} mandatory items have evidence`
          : `${mandatoryMissing} mandatory items missing evidence`,
    })

    // 3. Pending reviews
    checks.push({
      id: 'reviews',
      label: 'Evidence reviews completed',
      status: report.pending_matches === 0 ? 'pass' : report.pending_matches <= 5 ? 'warning' : 'fail',
      detail:
        report.pending_matches === 0
          ? 'All matches reviewed'
          : `${report.pending_matches} matches pending review`,
    })

    // 4. Tender status
    const isFinalized = tender.status === 'finalized'
    const isReady = tender.status === 'ready_for_review'
    checks.push({
      id: 'status',
      label: 'Tender finalized',
      status: isFinalized ? 'pass' : isReady ? 'warning' : 'fail',
      detail: isFinalized
        ? 'Tender has been finalized'
        : isReady
          ? 'Ready for review but not finalized'
          : `Current status: ${tender.status}`,
    })

    // 5. Deadline
    if (tender.submission_deadline) {
      const deadline = new Date(tender.submission_deadline)
      const now = new Date()
      const daysLeft = Math.ceil((deadline.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
      checks.push({
        id: 'deadline',
        label: 'Submission deadline',
        status: daysLeft > 7 ? 'pass' : daysLeft > 2 ? 'warning' : 'fail',
        detail:
          daysLeft < 0
            ? `Deadline passed ${Math.abs(daysLeft)} days ago`
            : daysLeft === 0
              ? 'Deadline is today'
              : `${daysLeft} days remaining`,
      })
    }

    // 6. Rejected matches without alternative
    const rejectedOnly = requirements.filter((r) => {
      const reqMatches = matches.filter((m) => m.requirement_id === r.id)
      return reqMatches.length > 0 && reqMatches.every((m) => m.review_status === 'rejected')
    }).length
    if (rejectedOnly > 0) {
      checks.push({
        id: 'rejected',
        label: 'Rejected without alternatives',
        status: 'fail',
        detail: `${rejectedOnly} requirements have only rejected evidence`,
      })
    }

    return checks
  }, [tender, report, requirements, matches])

  const manualDone = MANUAL_ITEMS.filter((i) => checked[i.id]).length

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* Left: Manual checklist */}
      <div className="rounded-xl border border-hairline bg-surface shadow-sm">
        <div className="border-b border-hairline px-4 py-3">
          <p className="text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
            Manual Checklist
          </p>
          <p className="mt-0.5 text-xs text-neutral-400">
            {manualDone} of {MANUAL_ITEMS.length} completed
          </p>
        </div>
        <div className="divide-y divide-hairline">
          {MANUAL_ITEMS.map((item) => {
            const isDone = checked[item.id] ?? false
            return (
              <label
                key={item.id}
                className="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-surface-muted/50"
              >
                <input
                  type="checkbox"
                  checked={isDone}
                  onChange={() => toggleItem(item.id)}
                  className="size-4 shrink-0 cursor-pointer rounded border-neutral-300"
                  style={{ accentColor: '#059669' }}
                />
                <span
                  className={[
                    'text-xs',
                    isDone ? 'text-neutral-400 line-through' : 'font-medium text-neutral-800',
                  ].join(' ')}
                >
                  {item.label}
                </span>
              </label>
            )
          })}
        </div>
      </div>

      {/* Right: AI findings */}
      <div className="rounded-xl border border-hairline bg-surface shadow-sm">
        <div className="border-b border-hairline px-4 py-3">
          <p className="text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
            AI Findings
          </p>
          <p className="mt-0.5 text-xs text-neutral-400">
            Automated checks from analysis data
          </p>
        </div>
        <div className="divide-y divide-hairline">
          {autoChecks.map((check) => {
            const isPass = check.status === 'pass'
            const isFail = check.status === 'fail'
            return (
              <div key={check.id} className="flex items-start gap-3 px-4 py-3">
                <span
                  className={[
                    'mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg',
                    isPass
                      ? 'bg-emerald-50 text-emerald-600'
                      : isFail
                        ? 'bg-rose-50 text-rose-500'
                        : 'bg-amber-50 text-amber-500',
                  ].join(' ')}
                >
                  {isPass ? (
                    <CheckCircleIcon className="size-4" />
                  ) : isFail ? (
                    <XCircleIcon className="size-4" />
                  ) : (
                    <CheckCircleIcon className="size-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-bold text-neutral-800">{check.label}</p>
                  <p className="text-[10px] text-neutral-500">{check.detail}</p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
