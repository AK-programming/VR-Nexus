/**
 * Compliance Matrix -- DPL-style editable table showing every requirement with
 * clause/page, description, mandatory flag, responsible person, supporting
 * document, deadline, and status.
 *
 * Matches the DPL TenderFlow compliance matrix layout: summary bar at top,
 * full-width table with inline editable inputs and selects per row.
 */

import { useCallback, useMemo, useState } from 'react'
import type { Requirement, EvidenceMatch } from '@/models/tenders'
import { SearchIcon } from '@/components/ui/icons'

type LocalOverrides = Record<
  string,
  { owner?: string; deadline?: string; notes?: string; status?: string }
>

function loadOverrides(tenderId: string): LocalOverrides {
  try {
    const raw = localStorage.getItem(`vrnexus.compliance.${tenderId}`)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveOverrides(tenderId: string, data: LocalOverrides) {
  try {
    localStorage.setItem(`vrnexus.compliance.${tenderId}`, JSON.stringify(data))
  } catch { /* quota exceeded */ }
}

const STATUS_OPTIONS = [
  { value: 'not-started', label: 'Not started' },
  { value: 'in-progress', label: 'In progress' },
  { value: 'review', label: 'Under review' },
  { value: 'approved', label: 'Approved' },
  { value: 'completed', label: 'Completed' },
]

const STATUS_DOT_COLOURS: Record<string, string> = {
  'not-started': 'bg-neutral-400',
  'in-progress': 'bg-amber-500',
  'review': 'bg-sky-500',
  'approved': 'bg-emerald-500',
  'completed': 'bg-emerald-600',
}

type Props = {
  tenderId: string
  requirements: Requirement[]
  matches: EvidenceMatch[]
}

export function ComplianceMatrix({ tenderId, requirements, matches }: Props) {
  const [search, setSearch] = useState('')
  const [overrides, setOverrides] = useState<LocalOverrides>(() => loadOverrides(tenderId))

  const matchesByReq = useMemo(() => {
    const map = new Map<string, EvidenceMatch[]>()
    for (const m of matches) {
      const list = map.get(m.requirement_id)
      if (list) list.push(m)
      else map.set(m.requirement_id, [m])
    }
    return map
  }, [matches])

  const rows = useMemo(() => {
    return requirements.map((req) => {
      const reqMatches = matchesByReq.get(req.id) ?? []
      const bestMatch = reqMatches.length > 0
        ? reqMatches.reduce((best, m) =>
            (m.confidence_score ?? 0) > (best.confidence_score ?? 0) ? m : best,
            reqMatches[0],
          )
        : null
      const ov = overrides[req.id] ?? {}
      return {
        requirement: req,
        bestMatch,
        owner: ov.owner ?? '',
        deadline: ov.deadline ?? '',
        notes: ov.notes ?? '',
        localStatus: ov.status ?? 'not-started',
      }
    })
  }, [requirements, matchesByReq, overrides])

  const filtered = useMemo(() => {
    if (!search.trim()) return rows
    const q = search.toLowerCase()
    return rows.filter(
      (r) =>
        r.requirement.description.toLowerCase().includes(q) ||
        r.requirement.clause_reference?.toLowerCase().includes(q) ||
        r.requirement.section_name?.toLowerCase().includes(q) ||
        r.owner.toLowerCase().includes(q),
    )
  }, [rows, search])

  const updateField = useCallback(
    (reqId: string, field: string, value: string) => {
      setOverrides((prev) => {
        const next = { ...prev, [reqId]: { ...prev[reqId], [field]: value } }
        saveOverrides(tenderId, next)
        return next
      })
    },
    [tenderId],
  )

  const completedCount = rows.filter(
    (r) => r.localStatus === 'completed' || r.localStatus === 'approved',
  ).length
  const mandatoryMissing = rows.filter(
    (r) => r.requirement.is_mandatory && !r.bestMatch,
  ).length

  return (
    <div className="flex flex-col gap-3">
      {/* Summary bar - DPL style */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-surface-muted px-4 py-3 text-xs text-neutral-600">
        <span>
          <strong className="text-neutral-900">{completedCount}/{requirements.length}</strong> requirements completed
        </span>
        {mandatoryMissing > 0 ? (
          <span>
            <strong className="text-neutral-900">{mandatoryMissing}</strong> mandatory items outstanding
          </span>
        ) : null}
        <span>Every AI extraction must be verified against the RFP page.</span>
        <div className="relative ml-auto">
          <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-neutral-400" />
          <input
            type="text"
            placeholder="Search requirements..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-48 rounded-lg border border-hairline bg-surface pl-8 pr-3 text-xs text-neutral-900 placeholder:text-neutral-400 focus:border-brand-400 focus:outline-none"
          />
        </div>
      </div>

      {/* Table - DPL advanced-table style */}
      <div className="overflow-x-auto rounded-xl border border-hairline bg-surface">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="bg-surface-muted text-left">
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Clause / Page
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500 min-w-[15rem]">
                Requirement
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Mandatory
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Responsible person
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Supporting document
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Internal deadline
              </th>
              <th className="px-3 py-2.5 text-[10px] font-extrabold uppercase tracking-wider text-neutral-500">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((row) => {
              const rid = row.requirement.id
              return (
                <tr key={rid} className="border-t border-hairline transition-colors hover:bg-surface-muted/40">
                  {/* Clause / Page */}
                  <td className="px-3 py-2.5 align-top" style={{ minWidth: 110 }}>
                    <input
                      type="text"
                      value={row.requirement.clause_reference ?? ''}
                      readOnly
                      className="mb-1 h-7 w-full rounded-lg border border-hairline bg-surface-muted px-2 text-xs font-mono text-neutral-700"
                      title="Clause reference"
                    />
                    <input
                      type="text"
                      value={row.requirement.section_name ?? ''}
                      readOnly
                      placeholder="Page"
                      className="h-7 w-full rounded-lg border border-hairline bg-surface-muted px-2 text-xs text-neutral-500"
                      title="Section / page"
                    />
                  </td>
                  {/* Requirement */}
                  <td className="px-3 py-2.5 align-top min-w-[15rem]">
                    <p className="text-xs leading-relaxed text-neutral-800">
                      {row.requirement.description.length > 200
                        ? row.requirement.description.slice(0, 200) + '...'
                        : row.requirement.description}
                    </p>
                  </td>
                  {/* Mandatory */}
                  <td className="px-3 py-2.5 align-top">
                    <span
                      className={[
                        'inline-block rounded-lg px-2 py-1 text-[10px] font-bold',
                        row.requirement.is_mandatory
                          ? 'bg-rose-100 text-rose-800'
                          : 'bg-neutral-100 text-neutral-600',
                      ].join(' ')}
                    >
                      {row.requirement.is_mandatory ? 'Mandatory' : 'Optional'}
                    </span>
                  </td>
                  {/* Responsible person */}
                  <td className="px-3 py-2.5 align-top">
                    <input
                      type="text"
                      value={row.owner}
                      placeholder="Assign..."
                      onChange={(e) => updateField(rid, 'owner', e.target.value)}
                      className="h-7 w-full min-w-[105px] rounded-lg border border-hairline bg-surface px-2 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-brand-400 focus:outline-none"
                    />
                  </td>
                  {/* Supporting document */}
                  <td className="px-3 py-2.5 align-top">
                    <input
                      type="text"
                      value={
                        row.bestMatch
                          ? (row.bestMatch.document_title ?? row.bestMatch.document_filename ?? 'Matched')
                          : row.notes
                      }
                      placeholder="Document..."
                      onChange={(e) => updateField(rid, 'notes', e.target.value)}
                      className="h-7 w-full min-w-[105px] rounded-lg border border-hairline bg-surface px-2 text-xs text-neutral-800 placeholder:text-neutral-400 focus:border-brand-400 focus:outline-none"
                    />
                  </td>
                  {/* Deadline */}
                  <td className="px-3 py-2.5 align-top">
                    <input
                      type="datetime-local"
                      value={row.deadline}
                      onChange={(e) => updateField(rid, 'deadline', e.target.value)}
                      className="h-7 w-full min-w-[105px] rounded-lg border border-hairline bg-surface px-2 text-xs text-neutral-800 focus:border-brand-400 focus:outline-none"
                    />
                  </td>
                  {/* Status */}
                  <td className="px-3 py-2.5 align-top">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={[
                          'size-2 shrink-0 rounded-full',
                          STATUS_DOT_COLOURS[row.localStatus] ?? 'bg-neutral-400',
                        ].join(' ')}
                      />
                      <select
                        value={row.localStatus}
                        onChange={(e) => updateField(rid, 'status', e.target.value)}
                        className="h-7 w-full min-w-[105px] rounded-lg border border-hairline bg-surface px-2 text-xs text-neutral-800 focus:border-brand-400 focus:outline-none"
                      >
                        {STATUS_OPTIONS.map((opt) => (
                          <option key={opt.value} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </td>
                </tr>
              )
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-12 text-center text-xs text-neutral-500">
                  {requirements.length === 0
                    ? 'No requirements were extracted from this tender.'
                    : 'No requirements match your search.'}
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
