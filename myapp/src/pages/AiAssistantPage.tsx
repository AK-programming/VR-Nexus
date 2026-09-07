/**
 * Ask the Evidence Library a question, or find the passages that answer it.
 *
 * This is the front end for the two library endpoints that had schemas and no UI:
 * `POST /api/library/ask` (retrieval-augmented generation) and `GET
 * /api/library/search` (retrieval alone). Both read the same index the tender
 * pipeline's Stage 3 matcher reads, so an answer here is grounded in exactly the
 * documents that will be matched against a tender — nothing is answered from the
 * model's own knowledge.
 *
 * Two modes, one box. **Ask** returns a written answer with the passages it was
 * built from; when the library cannot support the question — or when generation is
 * switched off (no `ANTHROPIC_API_KEY`) — the answer comes back `grounded: false` and
 * the retrieved passages are shown anyway, because they are the honest thing to
 * offer. **Find** skips generation and returns the ranked passages directly, which
 * is the truthful capability when there is no LLM configured at all.
 *
 * The conversation lives in component state only. Per the in-conversation preview
 * rules this app follows, nothing here touches browser storage — a reload starts a
 * fresh session, which is the right default for a question box over a shared
 * library rather than a private thread worth persisting.
 */

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentViewerPath } from '@/constants/routes'
import { CATEGORY_LABELS, DOCUMENT_CATEGORIES } from '@/models/documents'
import type {
  DocumentCategory,
  LibraryAnswer,
  LibrarySearchHit,
  LibrarySearchResponse,
} from '@/models/documents'
import { askLibrary, searchLibrary } from '@/services/documentService'
import { errorMessage } from '@/lib/apiClient'
import { Panel } from '@/components/dashboard/Panel'
import { ActionButton } from '@/components/ui/ActionButton'
import { AlertMessage } from '@/components/feedback/AlertMessage'
import {
  ChatIcon,
  CheckCircleIcon,
  FileTextIcon,
  SearchIcon,
  SendIcon,
  SparklesIcon,
  SpinnerIcon,
} from '@/components/ui/icons'

type AssistantMode = 'ask' | 'find'

type Turn =
  | { kind: 'ask'; question: string; answer: LibraryAnswer | null }
  | { kind: 'find'; query: string; result: LibrarySearchResponse | null }

const EXAMPLE_PROMPTS = [
  'What water-supply projects have we delivered?',
  'Summarise our quality-assurance methodology.',
  'Which case studies mention ISO 9001 certification?',
]

/**
 * Collapse repeated documents to a single row, keeping the highest similarity (and
 * any cited flag). The same case study often matches on several of its chunks;
 * listing it three times is noise, so we keep only its best hit per document.
 */
function dedupeByDocument(hits: LibrarySearchHit[]): LibrarySearchHit[] {
  const best = new Map<string, LibrarySearchHit>()
  for (const hit of hits) {
    const existing = best.get(hit.document_id)
    if (!existing) {
      best.set(hit.document_id, hit)
    } else if (hit.similarity > existing.similarity) {
      best.set(hit.document_id, { ...hit, cited: hit.cited || existing.cited })
    } else if (hit.cited && !existing.cited) {
      best.set(hit.document_id, { ...existing, cited: true })
    }
  }
  return Array.from(best.values()).sort((a, b) => b.similarity - a.similarity)
}

/** One retrieved passage, with a link to open the source document. */
function SourceCard({ hit }: { hit: LibrarySearchHit }) {
  const locator = [hit.section_name, hit.phase, hit.page_number ? `Page ${hit.page_number}` : null]
    .filter(Boolean)
    .join(' · ')

  return (
    <li
      className={[
        'rounded-xl border px-3.5 py-3',
        hit.cited ? 'border-brand-200 bg-selected' : 'border-hairline bg-surface',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-neutral-900">
            {hit.title || hit.original_filename}
          </p>
          <p className="mt-0.5 text-xs text-neutral-500">
            {CATEGORY_LABELS[hit.category] ?? hit.category}
            {locator ? ` · ${locator}` : ''}
          </p>
        </div>
        <span className="shrink-0 rounded-full border border-neutral-200 bg-neutral-100 px-2 py-0.5 text-[0.6875rem] font-semibold text-neutral-600 tabular-nums">
          {Math.round(hit.similarity * 100)}%
        </span>
      </div>

      <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-neutral-600">{hit.content}</p>

      <Link
        to={documentViewerPath(hit.document_id)}
        className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-600 underline-offset-2 hover:underline"
      >
        <FileTextIcon className="size-3.5" />
        Open document
      </Link>
    </li>
  )
}

function AskTurn({ turn }: { turn: Extract<Turn, { kind: 'ask' }> }) {
  const { answer } = turn
  const sources = answer ? dedupeByDocument(answer.sources) : []
  return (
    <div className="flex flex-col gap-3">
      <UserBubble text={turn.question} />
      {answer === null ? (
        <ThinkingBubble />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex items-start gap-2.5">
            <AssistantGlyph />
            <div className="min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-hairline bg-surface px-4 py-3">
              <p className="text-sm leading-relaxed whitespace-pre-wrap text-neutral-800">
                {answer.answer}
              </p>
              <p className="mt-2">
                {answer.grounded ? (
                  <span className="inline-flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-300">
                    <CheckCircleIcon className="size-3.5" />
                    Grounded in your evidence library
                  </span>
                ) : (
                  <span className="text-xs text-neutral-500">
                    Not grounded - the passages below are the closest matches; read them directly.
                  </span>
                )}
              </p>
            </div>
          </div>

          {sources.length > 0 ? (
            <div className="pl-9">
              <p className="mb-2 text-xs font-semibold tracking-wide text-neutral-500 uppercase">
                Sources
              </p>
              <ul className="flex flex-col gap-2">
                {sources.map((hit) => (
                  <SourceCard key={hit.chunk_id} hit={hit} />
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

function FindTurn({ turn }: { turn: Extract<Turn, { kind: 'find' }> }) {
  const { result } = turn
  const hits = result ? dedupeByDocument(result.hits) : []
  return (
    <div className="flex flex-col gap-3">
      <UserBubble text={turn.query} />
      {result === null ? (
        <ThinkingBubble />
      ) : (
        <div className="flex items-start gap-2.5">
          <AssistantGlyph />
          <div className="min-w-0 flex-1">
            {hits.length === 0 ? (
              <div className="rounded-2xl rounded-tl-sm border border-hairline bg-surface px-4 py-3 text-sm text-neutral-600">
                No passage in your library matched that. Try different wording, or add the
                relevant document from the Documents section.
              </div>
            ) : (
              <>
                <p className="mb-2 text-xs text-neutral-500">
                  {hits.length} passage{hits.length === 1 ? '' : 's'} from your
                  library:
                </p>
                <ul className="flex flex-col gap-2">
                  {hits.map((hit) => (
                    <SourceCard key={hit.chunk_id} hit={hit} />
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] rounded-2xl rounded-tr-sm bg-[linear-gradient(96deg,var(--color-brand-500)_0%,var(--color-brand-700)_100%)] px-4 py-2.5 text-sm text-white">
        {text}
      </p>
    </div>
  )
}

function AssistantGlyph() {
  return (
    <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600">
      <SparklesIcon className="size-4" />
    </span>
  )
}

function ThinkingBubble() {
  return (
    <div className="flex items-start gap-2.5">
      <AssistantGlyph />
      <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border border-hairline bg-surface px-4 py-3 text-sm text-neutral-500">
        <SpinnerIcon className="size-4 animate-spin" />
        Reading your library…
      </div>
    </div>
  )
}

export function AiAssistantPage() {
  const [mode, setMode] = useState<AssistantMode>('ask')
  const [category, setCategory] = useState<DocumentCategory | 'all'>('all')
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    /* Only follow a live conversation to the bottom. On mount (no turns) this
       must not fire, or the empty state scrolls the page down and the header and
       input are pushed out of view when the page opens. */
    if (turns.length === 0) return
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  async function submit(text: string) {
    const question = text.trim()
    if (!question || pending) return

    const minLength = mode === 'ask' ? 3 : 2
    if (question.length < minLength) {
      setError(
        mode === 'ask'
          ? 'Ask a question of at least a few words.'
          : 'Enter at least two characters to search.',
      )
      return
    }

    setError(null)
    setInput('')
    setPending(true)
    const cat = category === 'all' ? undefined : category

    /* Append the turn with an empty result first, so the question shows immediately
       and a spinner sits where the answer will land. */
    if (mode === 'ask') {
      setTurns((prev) => [...prev, { kind: 'ask', question, answer: null }])
    } else {
      setTurns((prev) => [...prev, { kind: 'find', query: question, result: null }])
    }

    try {
      if (mode === 'ask') {
        const answer = await askLibrary({ question, category: cat })
        setTurns((prev) =>
          prev.map((turn, index) =>
            index === prev.length - 1 && turn.kind === 'ask' ? { ...turn, answer } : turn,
          ),
        )
      } else {
        const result = await searchLibrary(question, { category: cat })
        setTurns((prev) =>
          prev.map((turn, index) =>
            index === prev.length - 1 && turn.kind === 'find' ? { ...turn, result } : turn,
          ),
        )
      }
    } catch (caught) {
      setError(errorMessage(caught))
      /* Drop the placeholder turn whose request failed, so a retry does not stack. */
      setTurns((prev) => prev.slice(0, -1))
    } finally {
      setPending(false)
    }
  }

  const hasConversation = turns.length > 0

  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col gap-4">
      <header>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
          AI Assistant
        </h1>
        <p className="mt-1 text-sm text-neutral-500">
          Ask a question and VR-Nexus answers from your Evidence Library - case studies,
          methodology and company documents - with the exact passages it drew on.
        </p>
      </header>

      <Panel
        title={mode === 'ask' ? 'Ask the library' : 'Find passages'}
        description={
          mode === 'ask'
            ? 'Answers are grounded only in your indexed documents.'
            : 'Semantic search over your indexed documents, no generation.'
        }
        action={
          <div className="inline-flex items-center gap-1 rounded-xl border border-hairline bg-surface-muted p-1">
            {(['ask', 'find'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                aria-pressed={mode === value}
                className={[
                  'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors duration-150',
                  mode === value
                    ? 'bg-surface text-neutral-900 shadow-sm'
                    : 'text-neutral-600 hover:text-neutral-900',
                ].join(' ')}
              >
                {value === 'ask' ? (
                  <SparklesIcon className="size-3.5" />
                ) : (
                  <SearchIcon className="size-3.5" />
                )}
                {value === 'ask' ? 'Ask' : 'Find'}
              </button>
            ))}
          </div>
        }
        flush
        className="min-h-0 flex-1"
      >
        {/* Conversation — the only scrolling area; the header above and the
            composer below stay put so the input is visible the moment the page
            opens. min-h-0 lets it shrink to whatever height is left. */}
        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-5">
          {!hasConversation ? (
            <div className="m-auto flex max-w-md flex-col items-center gap-4 py-8 text-center">
              <span className="flex size-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
                <ChatIcon className="size-6" />
              </span>
              <div>
                <p className="font-display text-base font-semibold text-neutral-900">
                  Ask your Evidence Library
                </p>
                <p className="mt-1 text-sm text-neutral-500">
                  Every answer is drawn from your indexed documents and shows its sources.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                {EXAMPLE_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={pending}
                    onClick={() => submit(prompt)}
                    className="rounded-xl border border-hairline bg-surface px-3.5 py-2 text-sm text-neutral-700 transition-colors hover:border-neutral-300 hover:bg-surface-muted disabled:opacity-60"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((turn, index) =>
              turn.kind === 'ask' ? (
                <AskTurn key={index} turn={turn} />
              ) : (
                <FindTurn key={index} turn={turn} />
              ),
            )
          )}
          <div ref={endRef} />
        </div>

        {/* Composer */}
        <div className="border-t border-hairline bg-surface px-5 py-4">
          {error ? (
            <div className="mb-3">
              <AlertMessage tone="error">{error}</AlertMessage>
            </div>
          ) : null}

          {/* `relative`: a sr-only label with no positioned ancestor anchors
              against the document root instead of this row, escaping every
              overflow-hidden/auto ancestor above it (the chat card, the page's
              scroll container, DashboardLayout's own h-dvh clip) and quietly
              growing document.documentElement past the viewport - which made
              the whole page scrollable, sidebar included. Giving this row its
              own containing block keeps the label local to it. */}
          <div className="relative flex items-end gap-2">
            <label className="sr-only" htmlFor="assistant-input">
              {mode === 'ask' ? 'Ask a question' : 'Search the library'}
            </label>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value as DocumentCategory | 'all')}
              className="h-11 shrink-0 rounded-xl border border-hairline bg-surface px-2.5 text-sm text-neutral-700 focus:border-brand-400 focus:ring-2 focus:ring-brand-200 focus:outline-none"
              aria-label="Filter by document category"
            >
              <option value="all">All types</option>
              {DOCUMENT_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {CATEGORY_LABELS[cat]}
                </option>
              ))}
            </select>

            <textarea
              id="assistant-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  submit(input)
                }
              }}
              rows={1}
              placeholder={
                mode === 'ask' ? 'Ask a question about your evidence…' : 'Search your library…'
              }
              className="max-h-32 min-h-[2.75rem] flex-1 resize-none rounded-xl border border-hairline bg-surface px-3.5 py-2.5 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-brand-400 focus:ring-2 focus:ring-brand-200 focus:outline-none"
            />

            <ActionButton
              variant="primary"
              size="md"
              trailingIcon={<SendIcon />}
              disabled={pending || input.trim().length === 0}
              onClick={() => submit(input)}
              className="h-11"
            >
              {mode === 'ask' ? 'Ask' : 'Search'}
            </ActionButton>
          </div>
          <p className="mt-2 text-xs text-neutral-400">
            Enter to send · Shift+Enter for a new line
          </p>
        </div>
      </Panel>
    </div>
  )
}
