/**
 * Tender Risk Scanner -- scans requirement descriptions for liability, SLA,
 * eligibility, payment, and security risk phrases, then groups and scores them.
 *
 * Purely client-side: it pattern-matches against the requirements that are
 * already loaded, so no extra API call is needed.
 */

import { useMemo, useState } from 'react'
import type { Requirement } from '@/models/tenders'
import { formatCount } from '@/lib/formatting'
import { ChevronDownIcon } from '@/components/ui/icons'

type RiskCategory = 'liability' | 'sla' | 'eligibility' | 'payment' | 'security' | 'penalty' | 'insurance'

type RiskPattern = {
  category: RiskCategory
  label: string
  keywords: string[]
}

const RISK_PATTERNS: RiskPattern[] = [
  {
    category: 'liability',
    label: 'Liability & Indemnity',
    keywords: [
      'liability', 'indemnify', 'indemnification', 'hold harmless',
      'consequential damage', 'unlimited liability', 'gross negligence',
      'sole risk', 'at own risk', 'waiver of liability',
    ],
  },
  {
    category: 'sla',
    label: 'SLA & Performance',
    keywords: [
      'service level', 'sla', 'response time', 'uptime', 'availability',
      'performance guarantee', 'performance bond', 'key performance',
      'kpi', 'turnaround time', 'within 24 hours', 'within 48 hours',
    ],
  },
  {
    category: 'eligibility',
    label: 'Eligibility & Qualification',
    keywords: [
      'minimum turnover', 'annual turnover', 'years of experience',
      'net worth', 'financial capacity', 'prequalification',
      'registration certificate', 'blacklisted', 'debarred',
      'joint venture', 'consortium requirement', 'iso certification',
      'mandatory qualification',
    ],
  },
  {
    category: 'payment',
    label: 'Payment & Financial',
    keywords: [
      'payment terms', 'retention', 'advance payment', 'milestone payment',
      'late payment', 'withholding', 'deduction', 'price adjustment',
      'escalation', 'foreign exchange', 'currency risk',
      'bid security', 'earnest money', 'bank guarantee',
    ],
  },
  {
    category: 'security',
    label: 'Security & Confidentiality',
    keywords: [
      'security clearance', 'background check', 'confidentiality',
      'non-disclosure', 'nda', 'data protection', 'gdpr', 'encryption',
      'intellectual property', 'proprietary', 'trade secret',
    ],
  },
  {
    category: 'penalty',
    label: 'Penalties & Liquidated Damages',
    keywords: [
      'penalty', 'liquidated damages', 'delay damages', 'forfeiture',
      'termination for default', 'termination for cause',
      'breach of contract', 'cure period', 'notice of default',
    ],
  },
  {
    category: 'insurance',
    label: 'Insurance & Bonding',
    keywords: [
      'insurance', 'professional indemnity', 'public liability',
      'workers compensation', 'performance bond', 'bid bond',
      'surety', 'fidelity guarantee', 'all-risk insurance',
    ],
  },
]

type RiskFinding = {
  requirement: Requirement
  category: RiskCategory
  matchedKeywords: string[]
  severity: 'high' | 'medium' | 'low'
}

function scanRequirements(requirements: Requirement[]): RiskFinding[] {
  const findings: RiskFinding[] = []

  for (const req of requirements) {
    const text = [
      req.description,
      req.section_name,
      req.clause_reference,
      req.evidence_description,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    for (const pattern of RISK_PATTERNS) {
      const matched = pattern.keywords.filter((kw) => text.includes(kw.toLowerCase()))
      if (matched.length > 0) {
        // Severity based on how many keywords matched and whether mandatory
        let severity: 'high' | 'medium' | 'low' = 'low'
        if (req.is_mandatory && matched.length >= 2) severity = 'high'
        else if (req.is_mandatory || matched.length >= 2) severity = 'medium'

        findings.push({
          requirement: req,
          category: pattern.category,
          matchedKeywords: matched,
          severity,
        })
      }
    }
  }

  return findings
}

const SEVERITY_COLOURS = {
  high: 'bg-rose-100 text-rose-800 border-rose-200',
  medium: 'bg-amber-100 text-amber-800 border-amber-200',
  low: 'bg-sky-100 text-sky-700 border-sky-200',
}

const SEVERITY_DOTS = {
  high: 'bg-rose-500',
  medium: 'bg-amber-500',
  low: 'bg-sky-500',
}

const CATEGORY_LABELS: Record<RiskCategory, string> = {
  liability: 'Liability & Indemnity',
  sla: 'SLA & Performance',
  eligibility: 'Eligibility & Qualification',
  payment: 'Payment & Financial',
  security: 'Security & Confidentiality',
  penalty: 'Penalties & Liquidated Damages',
  insurance: 'Insurance & Bonding',
}

type Props = {
  requirements: Requirement[]
}

export function RiskScanner({ requirements }: Props) {
  const findings = useMemo(() => scanRequirements(requirements), [requirements])
  const [expandedCategory, setExpandedCategory] = useState<RiskCategory | null>(null)

  const grouped = useMemo(() => {
    const map = new Map<RiskCategory, RiskFinding[]>()
    for (const f of findings) {
      const list = map.get(f.category)
      if (list) list.push(f)
      else map.set(f.category, [f])
    }
    return map
  }, [findings])

  const highCount = findings.filter((f) => f.severity === 'high').length
  const mediumCount = findings.filter((f) => f.severity === 'medium').length
  const lowCount = findings.filter((f) => f.severity === 'low').length

  const overallRisk = highCount > 3 ? 'High' : highCount > 0 || mediumCount > 5 ? 'Medium' : 'Low'
  const overallColour =
    overallRisk === 'High'
      ? 'text-rose-700 dark:text-rose-300'
      : overallRisk === 'Medium'
        ? 'text-amber-700 dark:text-amber-300'
        : 'text-emerald-700 dark:text-emerald-300'

  return (
    <div className="flex flex-col gap-6">
      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
          <p className="text-xs font-medium text-neutral-500">Overall Risk</p>
          <p className={['mt-1 font-display text-2xl font-semibold', overallColour].join(' ')}>
            {overallRisk}
          </p>
        </div>
        <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
          <p className="text-xs font-medium text-neutral-500">High Risk</p>
          <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-rose-700 dark:text-rose-300">
            {highCount}
          </p>
        </div>
        <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
          <p className="text-xs font-medium text-neutral-500">Medium Risk</p>
          <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-amber-700 dark:text-amber-300">
            {mediumCount}
          </p>
        </div>
        <div className="rounded-2xl border border-hairline bg-surface p-4 shadow-sm">
          <p className="text-xs font-medium text-neutral-500">Low Risk</p>
          <p className="mt-1 font-display text-2xl font-semibold tabular-nums text-sky-700 dark:text-sky-300">
            {lowCount}
          </p>
        </div>
      </div>

      {findings.length === 0 ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <p className="text-sm font-medium text-emerald-800">No risk phrases detected</p>
          <p className="mt-1 text-xs text-emerald-700">
            The scanner did not find known risk patterns in the extracted requirements.
            This does not guarantee the absence of risk. Always review the full tender document.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {Array.from(grouped.entries())
            .sort((a, b) => {
              // Sort by highest severity finding in the group
              const severityOrder = { high: 0, medium: 1, low: 2 }
              const aMax = Math.min(...a[1].map((f) => severityOrder[f.severity]))
              const bMax = Math.min(...b[1].map((f) => severityOrder[f.severity]))
              return aMax - bMax
            })
            .map(([category, catFindings]) => {
              const isOpen = expandedCategory === category
              const highInCat = catFindings.filter((f) => f.severity === 'high').length
              const medInCat = catFindings.filter((f) => f.severity === 'medium').length

              return (
                <div
                  key={category}
                  className="rounded-2xl border border-hairline bg-surface shadow-sm overflow-hidden"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedCategory(isOpen ? null : category)}
                    className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-surface-muted/50"
                  >
                    <ChevronDownIcon
                      className={[
                        'size-4 shrink-0 text-neutral-400 transition-transform duration-150',
                        isOpen ? '' : '-rotate-90',
                      ].join(' ')}
                    />
                    <div className="flex-1">
                      <span className="text-sm font-semibold text-neutral-900">
                        {CATEGORY_LABELS[category]}
                      </span>
                      <span className="ml-2 text-xs text-neutral-500">
                        {formatCount(catFindings.length)} findings
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      {highInCat > 0 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800">
                          <span className="size-1.5 rounded-full bg-rose-500" />
                          {highInCat} high
                        </span>
                      ) : null}
                      {medInCat > 0 ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                          <span className="size-1.5 rounded-full bg-amber-500" />
                          {medInCat} medium
                        </span>
                      ) : null}
                    </div>
                  </button>

                  {isOpen ? (
                    <div className="border-t border-hairline divide-y divide-hairline">
                      {catFindings.map((f, idx) => (
                        <div key={`${f.requirement.id}-${idx}`} className="px-5 py-3">
                          <div className="flex items-start gap-3">
                            <span
                              className={[
                                'mt-1 size-2 shrink-0 rounded-full',
                                SEVERITY_DOTS[f.severity],
                              ].join(' ')}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                {f.requirement.clause_reference ? (
                                  <span className="font-mono text-xs text-neutral-500">
                                    {f.requirement.clause_reference}
                                  </span>
                                ) : null}
                                <span
                                  className={[
                                    'inline-block rounded-full border px-2 py-0.5 text-xs font-medium',
                                    SEVERITY_COLOURS[f.severity],
                                  ].join(' ')}
                                >
                                  {f.severity}
                                </span>
                              </div>
                              <p className="mt-1 text-sm text-neutral-800">
                                {f.requirement.description.length > 200
                                  ? f.requirement.description.slice(0, 200) + '...'
                                  : f.requirement.description}
                              </p>
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {f.matchedKeywords.map((kw) => (
                                  <span
                                    key={kw}
                                    className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600"
                                  >
                                    {kw}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              )
            })}
        </div>
      )}
    </div>
  )
}
