/**
 * Activity — one reverse-chronological feed of what has happened in the workspace.
 *
 * Real events only, derived from the two things the API already exposes: tenders
 * (uploaded, and finalized) and library documents (added, and indexed). There is
 * no dedicated activity endpoint yet, so this composes the feed on the client from
 * `listTenders` + `listDocuments` — the same seam every other screen uses — and can
 * be swapped for a server feed later without changing the row rendering.
 */

import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ROUTES, tenderDetailPath, documentViewerPath } from '@/constants/routes'
import { tenderTitle } from '@/models/tenders'
import { CATEGORY_LABELS } from '@/models/documents'
import { listTenders } from '@/services/tenderService'
import { listDocuments } from '@/services/documentService'
import { useAsyncData } from '@/hooks/useAsyncData'
import { formatRelativeTime } from '@/lib/formatting'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { ErrorBlock, LoadingRows } from '@/components/feedback/DataState'
import { TableEmptyState } from '@/components/ui/DataTable'
import {
  ActivityIcon,
  CheckCircleIcon,
  DatabaseIcon,
  FileTextIcon,
  RefreshIcon,
  UploadIcon,
} from '@/components/ui/icons'

type Kind = 'tender_uploaded' | 'tender_finalized' | 'doc_added' | 'doc_indexed'

type Entry = {
  id: string
  kind: Kind
  description: string
  occurredAt: string
  to: string
}

const KIND_STYLE: Record<Kind, { icon: typeof FileTextIcon; classes: string }> = {
  tender_uploaded: { icon: UploadIcon, classes: 'bg-sky-50 text-sky-700' },
  tender_finalized: { icon: CheckCircleIcon, classes: 'bg-emerald-50 text-emerald-700' },
  doc_added: { icon: DatabaseIcon, classes: 'bg-brand-50 text-brand-700' },
  doc_indexed: { icon: FileTextIcon, classes: 'bg-neutral-100 text-neutral-600' },
}

export function ActivityPage() {
  const data = useAsyncData(
    async (signal) => {
      const [tenders, documents] = await Promise.all([
        listTenders({ limit: 100 }, { signal }),
        listDocuments({}, { signal }),
      ])
      return { tenders, documents }
    },
    [],
  )

  const entries = useMemo<Entry[]>(() => {
    const out: Entry[] = []
    for (const t of data.data?.tenders ?? []) {
      out.push({
        id: `t-up-${t.id}`,
        kind: 'tender_uploaded',
        description: `Tender uploaded - ${tenderTitle(t)}`,
        occurredAt: t.created_at,
        to: tenderDetailPath(t.id),
      })
      if (t.finalized_at) {
        out.push({
          id: `t-fin-${t.id}`,
          kind: 'tender_finalized',
          description: `Tender finalized - ${tenderTitle(t)}`,
          occurredAt: t.finalized_at,
          to: tenderDetailPath(t.id),
        })
      }
    }
    for (const d of data.data?.documents ?? []) {
      const title = d.title || d.original_filename
      out.push({
        id: `d-add-${d.id}`,
        kind: 'doc_added',
        description: `Added to library - ${title} (${CATEGORY_LABELS[d.category] ?? d.category})`,
        occurredAt: d.created_at,
        to: documentViewerPath(d.id),
      })
      if (d.indexed_at) {
        out.push({
          id: `d-idx-${d.id}`,
          kind: 'doc_indexed',
          description: `Indexed - ${title}`,
          occurredAt: d.indexed_at,
          to: documentViewerPath(d.id),
        })
      }
    }
    return out.sort((a, b) => b.occurredAt.localeCompare(a.occurredAt))
  }, [data.data])

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            Activity
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            Every upload, analysis and indexing run across your workspace.
          </p>
        </div>
        <ActionButton
          variant="secondary"
          size="sm"
          leadingIcon={<RefreshIcon />}
          disabled={data.isRefreshing}
          onClick={data.refetch}
        >
          Refresh
        </ActionButton>
      </header>

      <Panel title="Recent activity" description={`${entries.length} event${entries.length === 1 ? '' : 's'}`} flush>
        {data.status === 'error' && data.data === null ? (
          <ErrorBlock
            title="Activity could not be loaded"
            message={data.error ?? 'The request did not complete.'}
            offline={data.offline}
            onRetry={data.refetch}
          />
        ) : data.status === 'loading' && data.data === null ? (
          <LoadingRows rows={6} label="Loading activity" />
        ) : entries.length === 0 ? (
          <div className="py-10">
            <TableEmptyState
              icon={<ActivityIcon className="size-5" />}
              title="Nothing has happened yet"
              description="Upload a tender or add documents to your library, and it will show up here."
              action={
                <ActionButton variant="primary" size="sm" to={ROUTES.tenderUpload} leadingIcon={<UploadIcon />} className="mt-1">
                  Upload a tender
                </ActionButton>
              }
            />
          </div>
        ) : (
          <ul className="flex flex-col divide-y divide-hairline">
            {entries.map((entry) => {
              const style = KIND_STYLE[entry.kind]
              const Icon = style.icon
              return (
                <li key={entry.id}>
                  <Link
                    to={entry.to}
                    className="flex items-start gap-3 px-5 py-3.5 transition-colors duration-150 hover:bg-surface-muted"
                  >
                    <span className={['mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg [&>svg]:size-4', style.classes].join(' ')}>
                      <Icon />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-neutral-800">{entry.description}</span>
                      <span className="mt-0.5 block text-xs text-neutral-500 tabular-nums">
                        {formatRelativeTime(entry.occurredAt)}
                      </span>
                    </span>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>
    </div>
  )
}
