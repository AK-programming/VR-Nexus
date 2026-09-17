/**
 * Display formatting, in one place.
 *
 * These are the only functions allowed to turn data into prose. Panels call them
 * instead of reaching for `toLocaleString` inline, so "15 May 2025" cannot appear
 * as "May 15, 2025" two panels later, and a change of house style is one edit.
 *
 * Nothing here is locale-aware on purpose beyond the explicit tags below. The
 * product is a Pakistani tender tool and en-GB day-month ordering is what its
 * users read; picking up the browser's locale would give an American visitor a
 * different date order from the one on the tender document in front of them.
 */

/** "15 May 2025". Day first, month abbreviated, always with the year. */
export function formatShortDate(isoDate: string): string {
  const date = new Date(isoDate)

  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/** "16 May 2025". The long month, for the chart tooltip where there is room. */
export function formatLongDate(isoDate: string): string {
  const date = new Date(isoDate)

  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

/** "2:15 PM". For the Usage chart's per-call x-axis/tooltip, where the
 *  point is one API call rather than a whole day — see UsageDailyPoint's
 *  `time` field. `toLocaleTimeString` rather than a hand-rolled 12-hour
 *  conversion for the same reason the date formatters use `toLocaleDateString`:
 *  DST and locale edge cases are the runtime's problem, not ours. */
export function formatTimeOfDay(isoTimestamp: string): string {
  const date = new Date(isoTimestamp)

  if (Number.isNaN(date.getTime())) {
    return '-'
  }

  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
}

/**
 * "just now", "10 min ago", "2 hours ago", "3 days ago", then a date.
 *
 * Written out rather than handed to Intl.RelativeTimeFormat, which renders
 * "10 minutes ago" at full style and "10 min. ago" — with a stop — at short style
 * in some engines. A feed of timestamps needs to be scannable and identical
 * everywhere, and that is worth eight lines.
 */
export function formatRelativeTime(isoTimestamp: string, now: Date = new Date()): string {
  const then = new Date(isoTimestamp)

  if (Number.isNaN(then.getTime())) {
    return '-'
  }

  const seconds = Math.round((now.getTime() - then.getTime()) / 1000)

  /* A clock a few seconds fast should not produce "in 4 seconds". */
  if (seconds < 45) {
    return 'just now'
  }

  const minutes = Math.round(seconds / 60)
  if (minutes < 60) {
    return `${minutes} min ago`
  }

  const hours = Math.round(minutes / 60)
  if (hours < 24) {
    return hours === 1 ? '1 hour ago' : `${hours} hours ago`
  }

  const days = Math.round(hours / 24)
  if (days < 7) {
    return days === 1 ? 'yesterday' : `${days} days ago`
  }

  return formatShortDate(isoTimestamp)
}

/** "2,341". Grouped, never abbreviated — a tender count is not a vanity metric. */
export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

/** "+20%" / "-4%". The sign is part of the string so the caller cannot drop it. */
export function formatSignedPercent(value: number): string {
  const rounded = Math.round(value)
  return `${rounded > 0 ? '+' : ''}${rounded}%`
}

/** "13 GB". One decimal only when the value needs it, so 20 never reads "20.0". */
export function formatGigabytes(value: number): string {
  const isWhole = Number.isInteger(value)
  return `${isWhole ? value : value.toFixed(1)} GB`
}

/**
 * "8.4 MB", "412 KB", "0 bytes".
 *
 * 1024, not 1000. A file manager on every platform the reader uses reports binary
 * units, and a document library that disagrees with the operating system about how
 * big the same file is looks broken rather than pedantic.
 *
 * Bytes and KB get no decimal — a tenth of a kilobyte is noise — while MB and GB get
 * one, because the difference between 8.4 and 8.9 MB is the kind of thing a person
 * scanning a list actually uses. `formatGigabytes` above stays separate: it takes a
 * figure that is already in gigabytes, where this takes a raw byte count.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return '-'
  }

  if (bytes < 1024) {
    return `${Math.round(bytes)} ${bytes === 1 ? 'byte' : 'bytes'}`
  }

  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIndex = 0

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }

  /* KB whole, everything above it to one decimal — and `toFixed(1)` then trimmed, so
     a round 2.0 MB reads "2 MB" rather than announcing a precision it does not have. */
  const text = unitIndex === 0 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, '')

  return `${text} ${units[unitIndex]}`
}

/**
 * "Muhammad Afnan Khan" → "MA". Two letters at most, from the first and second
 * words, so the avatar never has to fit three characters into a 36px circle.
 *
 * Shared because the avatar appears twice — the rail's identity card and the
 * header's account button — and two implementations of this would eventually
 * disagree about someone with a middle name.
 */
export function formatInitials(name: string | null | undefined): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)

  if (words.length === 0) {
    return '-'
  }

  return words
    .slice(0, 2)
    .map((word) => word.charAt(0).toUpperCase())
    .join('')
}

/** "admin" → "Admin". The API sends roles lowercase; nothing displays them that way. */
export function formatRole(role: string | null | undefined): string {
  if (!role) {
    return ''
  }

  return role.charAt(0).toUpperCase() + role.slice(1)
}

/**
 * "Muhammad Afnan Khan" → "Muhammad".
 *
 * A greeting uses one name. Three is a form field being read back at you, and the
 * dashboard heading is the one place on the page written to a person rather than
 * about their data.
 */
export function formatFirstName(name: string | null | undefined): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)
  return words[0] ?? ''
}

/**
 * "$0.0042", "$1.23", "$0.00" — an estimated Anthropic API cost, never a
 * real invoice line, which is why every value this touches is labelled
 * "estimated" in the UI it appears in.
 *
 * A tender's per-chunk extraction cost is routinely a fraction of a cent,
 * so a flat two-decimal `toFixed(2)` would print "$0.00" for almost every
 * real call and make the feature look broken. This keeps enough
 * significant digits to show a non-zero value below a cent, and collapses
 * to a plain two-decimal figure once the amount is large enough that the
 * extra precision would just be noise.
 */
export function formatCostUsd(value: number): string {
  if (!Number.isFinite(value) || value === 0) {
    return '$0.00'
  }

  const abs = Math.abs(value)
  const decimals = abs < 0.01 ? 4 : abs < 1 ? 3 : 2
  return `$${value.toFixed(decimals)}`
}

/**
 * "842ms", "3.2s", "1m 14s" — a latency or elapsed-time figure. Milliseconds
 * below one second (most single API calls), one decimal of seconds below a
 * minute (a tender's total extraction time), minutes+seconds above that (a
 * large tender's full run) — so the number reads at whichever granularity
 * is actually meaningful at its own size.
 */
export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return '-'
  }

  if (ms < 1000) {
    return `${Math.round(ms)}ms`
  }

  const totalSeconds = ms / 1000
  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(1)}s`
  }

  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds - minutes * 60)
  return `${minutes}m ${seconds}s`
}
