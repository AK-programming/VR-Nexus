/**
 * The utility bar at the foot of the content column.
 *
 * It sits inside the scrolling area rather than pinned to the window, which is the
 * whole reason it is allowed to exist. A bar fixed to the bottom of the viewport
 * would spend 56px of every screen on a copyright line, and on a laptop that is
 * 56px taken from the chart. Here it appears when the reader reaches the end of
 * the page, which is when a version number is any use to them.
 *
 * The status dot is decoration — the sentence beside it carries the meaning, so a
 * reader who cannot distinguish the green loses nothing.
 */

export function Footer() {
  return (
    <footer className="border-t border-hairline px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex flex-col items-center gap-3 text-xs text-neutral-500 sm:flex-row sm:justify-between sm:gap-4">
        <p>&copy; {new Date().getFullYear()} VR-Nexus. All rights reserved.</p>

        <div className="flex items-center gap-4">
          <span>Version 1.0.0</span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-emerald-500" />
            All systems operational
          </span>
        </div>
      </div>
    </footer>
  )
}
