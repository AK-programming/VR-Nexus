/**
 * A ref for a popover/dropdown panel that closes itself on an outside click.
 *
 * Lifted out of dashboard/Header.tsx, which had this inline for its search
 * flyout and its notifications panel — the API Usage page's date-range menu
 * needs the exact same behaviour, and a third hand-copied `mousedown`
 * listener is how these quietly drift apart (one gets a `touchstart`
 * listener added for mobile, the other doesn't, and now they disagree).
 */
import { useEffect, useRef } from 'react'

export function useClickOutside<T extends HTMLElement = HTMLDivElement>(onOutside: () => void) {
  const ref = useRef<T>(null)
  useEffect(() => {
    function onDown(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        onOutside()
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onOutside])
  return ref
}
