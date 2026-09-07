/**
 * Evaluation Score Simulator -- DPL-style two-column layout with score rows
 * (criteria name + source, max input, estimate input) and a conic-gradient
 * score ring sidebar showing the projected total.
 */

import { useCallback, useMemo, useState } from 'react'
import type { Requirement, TenderDetail, TenderReport, ImpactBreakdown } from '@/models/tenders'
import { EVALUATION_IMPACT_LABELS } from '@/models/tenders'

type CategoryScore = {
  impact: string
  label: string
  marksAvailable: number
  marksCaptured: number
  estimatedScore: number
  requirementCount: number
}

type Props = {
  tender: TenderDetail
  report: TenderReport
  requirements: Requirement[]
}

export function EvaluationSimulator({ report, requirements }: Props) {
  const baseCategories: CategoryScore[] = useMemo(() => {
    return report.by_evaluation_impact.map((row: ImpactBreakdown) => ({
      impact: row.impact,
      label:
        EVALUATION_IMPACT_LABELS[row.impact as keyof typeof EVALUATION_IMPACT_LABELS] ??
        row.impact,
      marksAvailable: row.marks_available,
      marksCaptured: row.marks_captured,
      estimatedScore: row.marks_captured,
      requirementCount: row.requirement_count,
    }))
  }, [report.by_evaluation_impact])

  const [scores, setScores] = useState<Record<string, number>>(() => {
    const initial: Record<string, number> = {}
    for (const cat of baseCategories) {
      initial[cat.impact] = cat.marksCaptured
    }
    return initial
  })

  const updateScore = useCallback((impact: string, value: number) => {
    setScores((prev) => ({ ...prev, [impact]: value }))
  }, [])

  const categories = useMemo(() => {
    return baseCategories.map((cat) => ({
      ...cat,
      estimatedScore: scores[cat.impact] ?? cat.marksCaptured,
    }))
  }, [baseCategories, scores])

  const totalAvailable = categories.reduce((sum, c) => sum + c.marksAvailable, 0)
  const totalEstimated = categories.reduce((sum, c) => sum + c.estimatedScore, 0)
  const overallPercent = totalAvailable > 0 ? Math.round((totalEstimated / totalAvailable) * 100) : 0

  // Gaps: categories below 70%
  const gaps = categories.filter(
    (c) => c.marksAvailable > 0 && c.estimatedScore / c.marksAvailable < 0.7,
  )

  // Mandatory requirements without evidence
  const mandatoryMissing = requirements.filter(
    (r) => r.is_mandatory && r.match_count === 0,
  )

  const resetToActual = useCallback(() => {
    const reset: Record<string, number> = {}
    for (const cat of baseCategories) {
      reset[cat.impact] = cat.marksCaptured
    }
    setScores(reset)
  }, [baseCategories])

  // Conic gradient for the score ring
  const ringDeg = Math.round((overallPercent / 100) * 360)
  const ringColour = overallPercent >= 80 ? '#059669' : overallPercent >= 60 ? '#d97706' : '#e11d48'
  const ringBg = `conic-gradient(${ringColour} ${ringDeg}deg, #e5e7eb ${ringDeg}deg)`

  return (
    <div className="flex flex-col gap-4">
      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_.6fr]">
        {/* Left: Score rows */}
        <div className="rounded-xl border border-hairline bg-surface shadow-sm">
          <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
            <span className="text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
              Evaluation Criteria
            </span>
            <button
              type="button"
              onClick={resetToActual}
              className="rounded-lg px-2.5 py-1 text-[10px] font-bold text-brand-600 transition-colors hover:bg-brand-50"
            >
              Reset to actual
            </button>
          </div>

          {/* Header row */}
          <div className="grid grid-cols-[1fr_80px_90px] gap-2 border-b border-hairline bg-surface-muted px-4 py-2 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
            <span>Criteria</span>
            <span className="text-center">Max</span>
            <span className="text-center">Estimate</span>
          </div>

          {categories.length === 0 ? (
            <p className="px-4 py-12 text-center text-xs text-neutral-500">
              No scored evaluation categories were found in this tender.
            </p>
          ) : (
            <div className="divide-y divide-hairline">
              {categories.map((cat) => {
                const isGap = cat.marksAvailable > 0 && cat.estimatedScore / cat.marksAvailable < 0.7
                return (
                  <div
                    key={cat.impact}
                    className="grid grid-cols-[1fr_80px_90px] items-center gap-2 px-4 py-2.5 transition-colors hover:bg-surface-muted/40"
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-neutral-800">{cat.label}</p>
                      <p className="text-[10px] text-neutral-400">
                        {cat.requirementCount} requirement{cat.requirementCount !== 1 ? 's' : ''}
                        {' / '}current: {cat.marksCaptured}
                      </p>
                    </div>
                    <input
                      type="number"
                      value={cat.marksAvailable}
                      readOnly
                      className="h-7 w-full rounded-lg border border-hairline bg-surface-muted px-2 text-center text-xs font-mono text-neutral-600"
                    />
                    <input
                      type="number"
                      min={0}
                      max={cat.marksAvailable}
                      value={cat.estimatedScore}
                      onChange={(e) => {
                        const v = Math.min(cat.marksAvailable, Math.max(0, Number(e.target.value) || 0))
                        updateScore(cat.impact, v)
                      }}
                      className={[
                        'h-7 w-full rounded-lg border px-2 text-center text-xs font-mono focus:border-brand-400 focus:outline-none',
                        isGap
                          ? 'border-amber-300 bg-amber-50 text-amber-800'
                          : 'border-hairline bg-surface text-neutral-800',
                      ].join(' ')}
                    />
                  </div>
                )
              })}
            </div>
          )}

          {/* Total row */}
          {categories.length > 0 ? (
            <div className="grid grid-cols-[1fr_80px_90px] items-center gap-2 border-t border-hairline bg-surface-muted px-4 py-3">
              <span className="text-xs font-extrabold text-neutral-900">Total</span>
              <span className="text-center text-xs font-extrabold text-neutral-700">{totalAvailable}</span>
              <span className="text-center text-xs font-extrabold text-neutral-900">{totalEstimated}</span>
            </div>
          ) : null}
        </div>

        {/* Right: Score ring summary */}
        <div className="flex flex-col gap-4">
          <div className="flex flex-col items-center rounded-xl border border-hairline bg-surface p-5 shadow-sm">
            <span className="text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
              Projected Score
            </span>

            {/* Conic gradient ring */}
            <div className="relative mt-4 flex size-[120px] items-center justify-center rounded-full" style={{ background: ringBg }}>
              <div className="flex size-[88px] flex-col items-center justify-center rounded-full bg-surface">
                <span className="font-display text-2xl font-bold tabular-nums text-neutral-900">
                  {totalEstimated}
                </span>
                <span className="text-[10px] text-neutral-500">of {totalAvailable}</span>
              </div>
            </div>

            <p className="mt-3 text-lg font-bold tabular-nums text-neutral-900">{overallPercent}%</p>
            <p className="text-[10px] text-neutral-500">projected score</p>
          </div>

          {/* Gap warnings */}
          {gaps.length > 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
              <p className="text-[10px] font-extrabold uppercase tracking-wider text-amber-800">
                Gap Warnings
              </p>
              <div className="mt-2 flex flex-col gap-1.5">
                {gaps.map((g) => {
                  const pct = g.marksAvailable > 0 ? Math.round((g.estimatedScore / g.marksAvailable) * 100) : 0
                  return (
                    <p key={g.impact} className="text-xs text-amber-800">
                      <span className="font-bold">{g.label}</span> at {pct}% ({g.estimatedScore}/{g.marksAvailable})
                    </p>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* Mandatory missing */}
          {mandatoryMissing.length > 0 ? (
            <div className="rounded-xl border border-rose-200 bg-rose-50 p-4">
              <p className="text-[10px] font-extrabold uppercase tracking-wider text-rose-800">
                Mandatory Missing ({mandatoryMissing.length})
              </p>
              <div className="mt-2 flex flex-col gap-1">
                {mandatoryMissing.slice(0, 5).map((r) => (
                  <p key={r.id} className="text-xs text-rose-700">
                    <span className="font-mono">{r.clause_reference ?? 'N/A'}</span>{' '}
                    {r.description.length > 60 ? r.description.slice(0, 60) + '...' : r.description}
                  </p>
                ))}
                {mandatoryMissing.length > 5 ? (
                  <p className="text-[10px] text-rose-600">+{mandatoryMissing.length - 5} more</p>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
