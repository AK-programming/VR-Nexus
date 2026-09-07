/**
 * The assistant prompt box — the one loud surface on the page.
 *
 * Everything else here is a white card on a grey field, which is the right choice
 * for eight panels competing for the same glance but leaves the screen with no
 * centre. So this panel inverts: the sidebar's ink and the same radial red glow,
 * placed in the row where the eye lands after the numbers. One bold element, and the
 * discipline everywhere else is what makes it read as bold.
 *
 * It does not reuse `Panel`, which paints a white surface. It borrows the geometry —
 * same radius, same header padding — so it sits in the grid as a peer rather than an
 * exception.
 *
 * The form works. Submitting carries the text to the assistant route as `?q=`, and a
 * suggestion chip fills the field and focuses it rather than firing off on its own,
 * because a chip that submits gives you no chance to edit the question first.
 */

import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ROUTES } from '@/constants/routes'
import type { AssistantSuggestion } from '@/models/dashboard'
import { BRAND_SURFACE } from '@/components/ui/surfaces'
import { SendIcon, SparklesIcon } from '@/components/ui/icons'

type AiAssistantPanelProps = {
  suggestions: AssistantSuggestion[]
  className?: string
}

export function AiAssistantPanel({ suggestions, className }: AiAssistantPanelProps) {
  const [prompt, setPrompt] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  const trimmed = prompt.trim()
  const isEmpty = trimmed.length === 0

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isEmpty) {
      return
    }
    navigate(`${ROUTES.assistant}?q=${encodeURIComponent(trimmed)}`)
  }

  /* Not named `useSuggestion`. A function beginning with "use" is a hook by
     convention, and calling one from inside an onClick is exactly the rule
     violation the linter exists to catch. */
  function applySuggestion(suggestionPrompt: string) {
    setPrompt(suggestionPrompt)
    inputRef.current?.focus()
  }

  return (
    <section
      className={[
        'relative flex min-w-0 flex-col overflow-hidden rounded-2xl bg-ink-950 text-white shadow-panel',
        className ?? '',
      ].join(' ')}
    >
      {/* The rail's glow, mirrored. No image: this card is a different aspect ratio
          at every breakpoint and a crop that works at 1280px does not at 375px. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(120%_100%_at_100%_0%,rgba(232,21,27,0.32),transparent_65%)]"
      />

      <div className="relative flex min-h-0 flex-1 flex-col p-5">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-500/20 text-brand-300"
          >
            <SparklesIcon className="size-5" />
          </span>
          <div className="min-w-0">
            <h2 className="font-display text-base font-semibold tracking-tight text-white">
              AI Assistant
            </h2>
            <p className="mt-1 text-xs text-neutral-400">
              Ask anything about the tenders in your workspace
            </p>
          </div>
        </div>

        <div className="mt-5">
          <p className="text-[0.6875rem] font-semibold tracking-[0.14em] text-neutral-400 uppercase">
            Try asking
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion.id}
                type="button"
                onClick={() => applySuggestion(suggestion.prompt)}
                className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-neutral-200 transition-colors duration-150 hover:border-white/30 hover:bg-white/10 hover:text-white focus-visible:outline-brand-300"
              >
                {suggestion.prompt}
              </button>
            ))}
          </div>
        </div>

        {/* mt-auto pins the form to the bottom when the grid gives this card more
            height than its content needs, so it lines up with its neighbours. */}
        {/* `relative` gives the sr-only label below a containing block of its own
            - without one it positions against the document root and can silently
            grow page scroll height. See AiAssistantPage.tsx's composer for the
            full story; same footgun, smaller blast radius here. */}
        <form onSubmit={handleSubmit} className="relative mt-auto flex items-center gap-2.5 pt-6">
          <label htmlFor="assistant-prompt" className="sr-only">
            Ask the assistant a question
          </label>
          <input
            ref={inputRef}
            id="assistant-prompt"
            name="prompt"
            type="text"
            autoComplete="off"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Ask about a tender…"
            className="h-11 min-w-0 flex-1 rounded-xl border border-white/15 bg-white/5 px-4 text-sm text-white transition-colors duration-150 placeholder:text-neutral-400 focus:border-brand-400 focus:bg-white/10 focus-visible:outline-brand-300"
          />
          <button
            type="submit"
            disabled={isEmpty}
            aria-label="Send question to the assistant"
            className={[
              'flex size-11 shrink-0 items-center justify-center rounded-xl transition-colors duration-150 focus-visible:outline-brand-300',
              isEmpty
                ? 'cursor-not-allowed border border-white/15 bg-white/5 text-neutral-400'
                : BRAND_SURFACE,
            ].join(' ')}
          >
            <SendIcon className="size-5" />
          </button>
        </form>
      </div>
    </section>
  )
}
