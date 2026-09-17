/**
 * Whether the user asked the OS for less motion, kept live.
 *
 * Read synchronously in the initialiser rather than in an effect: Recharts (and
 * any other chart) starts its draw animation on first render, and an effect that
 * lands after paint would switch the animation off only once the user had
 * already seen it play once.
 *
 * Pulled out of AnalysisOverview.tsx, which had this inline first — a second
 * chart (the API Usage daily chart) needs the exact same behaviour, and a
 * second hand-copied `matchMedia` listener is how these two quietly drift.
 */
import { useEffect, useState } from 'react'

export function usePrefersReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')

    function handleChange(event: MediaQueryListEvent) {
      setPrefersReduced(event.matches)
    }

    query.addEventListener('change', handleChange)
    return () => query.removeEventListener('change', handleChange)
  }, [])

  return prefersReduced
}
