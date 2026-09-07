/**
 * One extracted requirement, with the evidence that answers it and the controls
 * to accept, reject or reassign each match.
 *
 * This is the heart of the review workspace — the clause-by-clause pairing the
 * whole pipeline exists to produce. The row collapsed is scannable (what the
 * requirement is, whether it is covered, how many marks ride on it); expanded it
 * is actionable (each candidate document, its confidence, and the reviewer's
 * decision). The AI never finalises: every match arrives PENDING or AUTO, and a
 * person confirms it here before the output is locked in.
 *
 * `coverage` mirrors the server's `_requirement_covered` rule exactly so the chip
 * on this card and the marks total in the summary can never disagree: a
 * requirement is covered by an accepted match, or an auto-match not yet rejected.
 */

import { useId, useState } from 'react'
import type { EvidenceMatch, Requirement } from '@/models/tenders'
import {
  EVALUATION_IMPACT_LABELS,
  MATCH_TYPE_LABELS,
  requirementPriority,
  REQUIREMENT_PRIORITY_LABELS,
} from '@/models/tenders'
import type { MatchReviewAction } from '@/models/tenders'
import { CATEGORY_LABELS } from '@/models/documents'
import type { DocumentCategory } from '@/models/documents'
import { ActionButton } from '@/components/ui/ActionButton'
import {
  BanIcon,
  CheckIcon,
  ChevronDownIcon,
  FileTextIcon,
  RefreshIcon,
} from '@/components/ui/icons'

export type CoverageState = 'matched' | 'review' | 'missing' | 'not_required'

/** The server's coverage rule, restated on the client so the two never drift. */
export function requirementCoverage(req: Requirement, matches: EvidenceMatch[]): CoverageState {
  if (!req.evidence_required) return 'not_required'
  if (
    matches.some(
      (m) =>
        m.review_status === 'accepted' ||
        (m.match_type === 'auto' && m.review_status !== 'rejected'),
    )
  ) {
    return 'matched'
  }
  if (matches.some((m) => m.match_type === 'suggested' && m.review_status === 'pending')) {
    return 'review'
  }
  return 'missing'
}

/**
 * RFP boilerplate that virtually every tender opens with — a disclaimer
 * paragraph or an executive-summary preamble, LLM-extracted one sentence at a
 * time because each sentence looked clause-shaped on its own. None of it asks
 * the bidder to prove anything, and section_name is the only field the
 * extractor gives us that reliably tells this apart from an actual
 * requirement: a real functional/eligibility clause in this tender's data
 * lives under sections like "Functional Requirements" or "General/Front
 * Matter", never under these two.
 *
 * Deliberately a short, conservative allowlist rather than a broader "no
 * mandatory flag, no marks, no evaluation impact" rule — most of this
 * tender's genuine functional requirements ALSO carry none of those (they're
 * plain feature bullets), so that broader rule would silently drop real
 * compliance rows. Tune this list per how a tender labels its own front
 * matter, not by loosening the second condition.
 */
const NARRATIVE_SECTION_NAMES = new Set(['disclaimer', 'executive summary'])

/** True for a row that reads as scene-setting narrative rather than a real,
 * provable requirement — see NARRATIVE_SECTION_NAMES above. */
export function isNarrativeBoilerplate(req: Requirement): boolean {
  const section = (req.section_name ?? '').trim().toLowerCase()
  if (!NARRATIVE_SECTION_NAMES.has(section)) return false
  return (
    !req.is_mandatory &&
    !req.evidence_required &&
    !req.evaluation_impact &&
    (req.marks == null || req.marks === 0)
  )
}

const COVERAGE_STYLES: Record<CoverageState, { label: string; classes: string }> = {
  matched: { label: 'Matched', classes: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  review: { label: 'Review', classes: 'border-amber-200 bg-amber-50 text-amber-800' },
  missing: { label: 'Missing', classes: 'border-rose-200 bg-rose-50 text-rose-800' },
  not_required: {
    label: 'No evidence needed',
    classes: 'border-neutral-200 bg-neutral-100 text-neutral-600',
  },
}

const REVIEW_STYLES: Record<EvidenceMatch['review_status'], string> = {
  pending: 'border-neutral-200 bg-neutral-100 text-neutral-600',
  accepted: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  rejected: 'border-rose-200 bg-rose-50 text-rose-800',
  reassigned: 'border-sky-200 bg-sky-50 text-sky-800',
}

const REVIEW_LABELS: Record<EvidenceMatch['review_status'], string> = {
  pending: 'Pending',
  accepted: 'Accepted',
  rejected: 'Rejected',
  reassigned: 'Reassigned',
}

function Chip({ children, className }: { children: React.ReactNode; className: string }) {
  return (
    <span
      className={[
        'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5',
        'text-[0.6875rem] font-semibold whitespace-nowrap',
        className,
      ].join(' ')}
    >
      {children}
    </span>
  )
}

/** Highest confidence among a requirement's candidate matches, as a percent. */
function bestConfidence(matches: EvidenceMatch[]): number | null {
  const scores = matches
    .map((m) => m.confidence_score)
    .filter((s): s is number => typeof s === 'number')
  if (scores.length === 0) return null
  return Math.round(Math.max(...scores) * 100)
}

type RequirementReviewCardProps = {
  index: number
  requirement: Requirement
  matches: EvidenceMatch[]
  /** True once the tender is finalized — the actions become read-only. */
  locked: boolean
  /** The match id currently being written, so its row can show a busy state. */
  busyMatchId: string | null
  onReview: (matchId: string, action: MatchReviewAction) => void
  onReassign: (match: EvidenceMatch) => void
}

export function RequirementReviewCard({
  index,
  requirement,
  matches,
  locked,
  busyMatchId,
  onReview,
  onReassign,
}: RequirementReviewCardProps) {
  const [open, setOpen] = useState(false)
  const bodyId = useId()

  const coverage = requirementCoverage(requirement, matches)
  const coverageStyle = COVERAGE_STYLES[coverage]
  const confidence = bestConfidence(matches)
  const priority = requirementPriority(requirement.is_mandatory)

  /* Prefer the tender's own page wording ("1-2") over the sortable integer. */
  const pageText = requirement.page_label ?? (
    requirement.page_number != null ? String(requirement.page_number) : null
  )

  const locator = [
    pageText ? `Page ${pageText}` : null,
    requirement.section_name,
    requirement.clause_reference,
  ]
    .filter(Boolean)
    .join(' · ')

  /* The per-member responsibility split plus anything extra this tender carried,
     shown verbatim so the screen and the exported tracker agree. */
  const detailEntries = (
    [
      ['Responsibility', requirement.responsibility],
      ['DPL', requirement.dpl],
      ['PRIME', requirement.prime],
      ['The Tulepaak', requirement.the_t],
      ['Joint', requirement.joint_responsibility],
      ...Object.entries(requirement.extra_fields ?? {}),
    ] as [string, string | null][]
  ).filter((entry): entry is [string, string] => Boolean(entry[1]))

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={bodyId}
        className="flex w-full items-start gap-3 px-5 py-4 text-left transition-colors duration-150 hover:bg-surface-muted"
      >
        <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700 tabular-nums">
          {index}
        </span>

        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-neutral-900">
            {requirement.description}
          </span>
          {locator ? (
            <span className="mt-1 block text-xs text-neutral-500">{locator}</span>
          ) : null}

          <span className="mt-2 flex flex-wrap items-center gap-1.5">
            {requirement.mandatory_raw || priority === 'mandatory' ? (
              <Chip
                className={
                  priority === 'mandatory'
                    ? 'border-rose-200 bg-rose-50 text-rose-700'
                    : 'border-neutral-200 bg-neutral-100 text-neutral-700'
                }
              >
                {requirement.mandatory_raw || REQUIREMENT_PRIORITY_LABELS.mandatory}
              </Chip>
            ) : null}
            {requirement.evaluation_impact_raw || requirement.evaluation_impact ? (
              <Chip className="border-neutral-200 bg-neutral-100 text-neutral-700">
                {requirement.evaluation_impact_raw ||
                  (requirement.evaluation_impact
                    ? EVALUATION_IMPACT_LABELS[requirement.evaluation_impact]
                    : '')}
              </Chip>
            ) : null}
            {requirement.marks != null ? (
              <Chip className="border-neutral-200 bg-neutral-100 text-neutral-700">
                {requirement.marks} {requirement.marks === 1 ? 'mark' : 'marks'}
              </Chip>
            ) : null}
            {confidence != null ? (
              <Chip className="border-neutral-200 bg-neutral-100 text-neutral-700 tabular-nums">
                {confidence}% match
              </Chip>
            ) : null}
          </span>
        </span>

        <span className="flex shrink-0 items-center gap-2">
          <Chip className={coverageStyle.classes}>{coverageStyle.label}</Chip>
          <ChevronDownIcon
            className={[
              'size-4 text-neutral-400 transition-transform duration-150',
              open ? 'rotate-180' : '',
            ].join(' ')}
          />
        </span>
      </button>

      {open ? (
        <div id={bodyId} className="border-t border-hairline bg-surface-muted/40 px-5 py-4">
          {detailEntries.length > 0 ? (
            <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
              {detailEntries.map(([label, value]) => (
                <div key={label} className="min-w-0">
                  <dt className="text-[0.6875rem] font-medium tracking-wide text-neutral-500 uppercase">
                    {label}
                  </dt>
                  <dd className="truncate text-xs text-neutral-800" title={value}>
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          {requirement.evidence_description ? (
            <p className="mb-3 text-xs text-neutral-600">
              <span className="font-semibold text-neutral-700">Evidence sought: </span>
              {requirement.evidence_description}
            </p>
          ) : null}

          {matches.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-neutral-500">
              <FileTextIcon className="size-4 text-neutral-400" />
              {requirement.evidence_required
                ? 'No candidate document was found in your library for this requirement.'
                : 'This requirement does not need a supporting document.'}
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {matches.map((match) => {
                const busy = busyMatchId === match.id
                const pct =
                  typeof match.confidence_score === 'number'
                    ? Math.round(match.confidence_score * 100)
                    : null
                return (
                  <li
                    key={match.id}
                    className="rounded-xl border border-hairline bg-surface px-3.5 py-3"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-neutral-900">
                          {match.document_title || match.document_filename || 'Untitled document'}
                        </p>
                        <p className="mt-1 flex flex-wrap items-center gap-1.5">
                          {match.document_category ? (
                            <Chip className="border-neutral-200 bg-neutral-100 text-neutral-600">
                              {CATEGORY_LABELS[match.document_category as DocumentCategory] ??
                                match.document_category}
                            </Chip>
                          ) : null}
                          <Chip className="border-neutral-200 bg-neutral-100 text-neutral-600">
                            {MATCH_TYPE_LABELS[match.match_type]}
                          </Chip>
                          {pct != null ? (
                            <Chip className="border-neutral-200 bg-neutral-100 text-neutral-600 tabular-nums">
                              {pct}% confidence
                            </Chip>
                          ) : null}
                          <Chip className={REVIEW_STYLES[match.review_status]}>
                            {REVIEW_LABELS[match.review_status]}
                          </Chip>
                        </p>
                      </div>

                      {!locked ? (
                        <div className="flex shrink-0 flex-wrap gap-1.5">
                          <ActionButton
                            variant={match.review_status === 'accepted' ? 'primary' : 'secondary'}
                            size="sm"
                            leadingIcon={<CheckIcon />}
                            disabled={busy}
                            onClick={() => onReview(match.id, 'accept')}
                          >
                            Accept
                          </ActionButton>
                          <ActionButton
                            variant={match.review_status === 'rejected' ? 'danger' : 'secondary'}
                            size="sm"
                            leadingIcon={<BanIcon />}
                            disabled={busy}
                            onClick={() => onReview(match.id, 'reject')}
                          >
                            Reject
                          </ActionButton>
                          <ActionButton
                            variant="secondary"
                            size="sm"
                            leadingIcon={<RefreshIcon />}
                            disabled={busy}
                            onClick={() => onReassign(match)}
                          >
                            Reassign
                          </ActionButton>
                        </div>
                      ) : null}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
