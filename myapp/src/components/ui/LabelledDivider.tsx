/**
 * A hairline rule with a word set into it — the "or" between the primary action
 * and the alternative one.
 *
 * The label is uppercased in CSS rather than in the string so callers pass real
 * words ("or") and the component owns how they are presented.
 */
export function LabelledDivider({ label }: { label: string }) {
  return (
    /* The rule is decoration around a word that is already in the reading order,
       so the whole thing is hidden from assistive tech to avoid announcing "or"
       as if it were a heading between two buttons. */
    <div className="flex items-center gap-4" aria-hidden="true">
      <span className="h-px flex-1 bg-hairline" />
      <span className="font-display text-[11px] font-semibold tracking-[0.22em] text-neutral-400 uppercase">
        {label}
      </span>
      <span className="h-px flex-1 bg-hairline" />
    </div>
  )
}
