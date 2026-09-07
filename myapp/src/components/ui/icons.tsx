/**
 * Every icon in the product, drawn by hand.
 *
 * No icon package: a dependency that ships 1,000 glyphs to render fifty-odd is a bad
 * trade, and drawing them here means they share one grid (24x24), one stroke
 * weight (1.75) and one set of caps, which is what actually makes a set look like
 * a set. Stroke is `currentColor`, so an icon inherits the colour of whatever it
 * sits in and never needs a colour prop.
 *
 * All are aria-hidden. An icon next to a label is decoration; an icon that is the
 * only content of a button gets its name from that button's aria-label instead.
 *
 * One glyph, one meaning, wherever it appears: the bar chart is "analysis" in the
 * sidebar, on the stat tile and on the quick-action card, so a reader learns it
 * once. Where a convention exists it wins over invention. The one departure is
 * Settings, drawn as sliders rather than a cog — a six-tooth gear turns to mud at
 * 20px, and sliders survive the size with the label beside them doing the naming.
 */

type IconProps = {
  className?: string
}

/** Shared attributes, so no icon can drift off the grid or change stroke weight. */
const strokeIcon = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.75,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const

export function MailIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="2.75" y="4.75" width="18.5" height="14.5" rx="2.5" />
      <path d="m3.75 7.75 7.35 4.9a1.6 1.6 0 0 0 1.8 0l7.35-4.9" />
    </svg>
  )
}

export function LifeBuoyIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.25" />
      <circle cx="12" cy="12" r="3.25" />
      <path d="m6.15 6.15 3.5 3.5M14.35 14.35l3.5 3.5M17.85 6.15l-3.5 3.5M9.65 14.35l-3.5 3.5" />
    </svg>
  )
}

export function LockIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="4.25" y="10.25" width="15.5" height="9.5" rx="2.25" />
      <path d="M8 10.25V7.6a4 4 0 0 1 8 0v2.65" />
      <path d="M12 14v2.25" />
    </svg>
  )
}

export function UserIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="8.25" r="3.75" />
      <path d="M4.75 19.75a7.25 7.25 0 0 1 14.5 0" />
    </svg>
  )
}

export function UserPlusIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="10" cy="8.25" r="3.5" />
      <path d="M3.75 19.75a6.25 6.25 0 0 1 12.5 0" />
      <path d="M18.75 7.25v5M16.25 9.75h5" />
    </svg>
  )
}

export function ShieldCheckIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 3.25l7 2.55v5.9c0 4.2-2.9 7.55-7 8.95-4.1-1.4-7-4.75-7-8.95V5.8Z" />
      <path d="m9 12.2 2.15 2.1L15.25 10.25" />
    </svg>
  )
}

export function PhoneIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M7.6 3.75H5.5A1.75 1.75 0 0 0 3.75 5.5c0 8.15 6.6 14.75 14.75 14.75a1.75 1.75 0 0 0 1.75-1.75v-2.1a1.75 1.75 0 0 0-1.4-1.72l-2.55-.51a1.75 1.75 0 0 0-1.74.73l-.68.97a11.6 11.6 0 0 1-5.05-5.05l.97-.68a1.75 1.75 0 0 0 .73-1.74L9.32 5.15A1.75 1.75 0 0 0 7.6 3.75Z" />
    </svg>
  )
}

export function BuildingIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.75 20.25V5.5a1.75 1.75 0 0 1 1.75-1.75h6a1.75 1.75 0 0 1 1.75 1.75v14.75" />
      <path d="M14.25 10.25h3.25a1.75 1.75 0 0 1 1.75 1.75v8.25" />
      <path d="M3 20.25h18" />
      <path d="M8 7.75h2.75M8 11.25h2.75M8 14.75h2.75" />
    </svg>
  )
}

export function EyeIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M2.5 12S6 5.9 12 5.9 21.5 12 21.5 12 18 18.1 12 18.1 2.5 12 2.5 12Z" />
      <circle cx="12" cy="12" r="3.25" />
    </svg>
  )
}

export function EyeOffIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m4 4 16 16" />
      <path d="M9.9 6.15A9.7 9.7 0 0 1 12 5.9c6 0 9.5 6.1 9.5 6.1a17.9 17.9 0 0 1-2.6 3.42" />
      <path d="M6.65 8.1A17.7 17.7 0 0 0 2.5 12S6 18.1 12 18.1c.85 0 1.64-.09 2.37-.26" />
      <path d="M9.88 9.88a3.25 3.25 0 0 0 4.24 4.24" />
    </svg>
  )
}

export function ArrowRightIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.75 12h13.5" />
      <path d="m13 6.75 5.25 5.25L13 17.25" />
    </svg>
  )
}

export function CheckIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className} strokeWidth={2.5}>
      <path d="m5 12.5 4.5 4.5L19 7.25" />
    </svg>
  )
}

export function AlertTriangleIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 4.5 21 19.5H3Z" />
      <path d="M12 9.75v4.25" />
      <path d="M12 16.85v.1" />
    </svg>
  )
}

export function InfoIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 11.25v5" />
      <path d="M12 7.9v.1" />
    </svg>
  )
}

export function ClockIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 7.25V12l3.25 2" />
    </svg>
  )
}

export function BanIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="m6.1 6.1 11.8 11.8" />
    </svg>
  )
}

export function SignalOffIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m4 4 16 16" />
      <path d="M2.75 8.9A13.2 13.2 0 0 1 8.5 6.2" />
      <path d="M15.1 6.6a13.2 13.2 0 0 1 6.15 2.3" />
      <path d="M6.15 12.35a9.2 9.2 0 0 1 2.6-1.5" />
      <path d="M14.6 11a9.2 9.2 0 0 1 3.25 1.85" />
      <path d="M9.6 15.75a4.7 4.7 0 0 1 4.55.15" />
      <path d="M12 19.15v.1" />
    </svg>
  )
}

/**
 * The only icon that animates. `animate-spin` is applied by the caller, so a
 * reduced-motion preference — which caps animation duration globally in
 * index.css — quietly stops it rather than needing a second variant here.
 */
export function SpinnerIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className} strokeWidth={2.25}>
      <circle cx="12" cy="12" r="8.75" opacity="0.3" />
      <path d="M20.75 12A8.75 8.75 0 0 0 12 3.25" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Navigation                                                                 */
/* -------------------------------------------------------------------------- */

/** Dashboard. Four panes, evenly gapped — the overview, not a menu. */
export function GridIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="3.75" y="3.75" width="6.5" height="6.5" rx="1.75" />
      <rect x="13.75" y="3.75" width="6.5" height="6.5" rx="1.75" />
      <rect x="3.75" y="13.75" width="6.5" height="6.5" rx="1.75" />
      <rect x="13.75" y="13.75" width="6.5" height="6.5" rx="1.75" />
    </svg>
  )
}

/** Analysis, everywhere it appears: the nav item, the stat tile, the action card. */
export function BarChartIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.75 20.25h14.5" />
      <path d="M8 20.25v-6.5" />
      <path d="M12 20.25v-11" />
      <path d="M16 20.25v-8.25" />
    </svg>
  )
}

/** A single document. */
export function FileTextIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M13.75 3.75H7A1.75 1.75 0 0 0 5.25 5.5v13A1.75 1.75 0 0 0 7 20.25h10a1.75 1.75 0 0 0 1.75-1.75V8.75Z" />
      <path d="M13.75 3.75v5h5" />
      <path d="M8.75 13.25h6.5" />
      <path d="M8.75 16.25h4.25" />
    </svg>
  )
}

/** A collection of documents — a project, or the document library. */
export function FolderIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M20.25 18.5a1.75 1.75 0 0 1-1.75 1.75h-13a1.75 1.75 0 0 1-1.75-1.75V6.75A1.75 1.75 0 0 1 5.5 5h3.75l2 2.75h7.25a1.75 1.75 0 0 1 1.75 1.75Z" />
    </svg>
  )
}

/** The assistant. Also marks anything the model produced rather than a person. */
export function SparklesIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 3.25l1.7 4.55 4.55 1.7-4.55 1.7L12 15.75l-1.7-4.55L5.75 9.5l4.55-1.7Z" />
      <path d="M18.25 15.5l.75 2 2 .75-2 .75-.75 2-.75-2-2-.75 2-.75Z" />
    </svg>
  )
}

/** Activity. A trace, not a list — it reads as "what happened, over time". */
export function ActivityIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M3.75 12h3.5l2.25-5.5 3.75 11 2.25-5.5h4.75" />
    </svg>
  )
}

/**
 * Settings. Sliders rather than a cog: the teeth of a gear collapse into a blur
 * at the 20px this renders at, and the word "Settings" sits next to it anyway.
 */
export function SettingsIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.75 8h2.5" />
      <path d="M11.75 8h7.5" />
      <circle cx="9.5" cy="8" r="2.25" />
      <path d="M4.75 16h7.5" />
      <path d="M16.75 16h2.5" />
      <circle cx="14.5" cy="16" r="2.25" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Header and chrome                                                          */
/* -------------------------------------------------------------------------- */

/** The signed-in person, in an avatar-shaped frame. */
export function UserCircleIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <circle cx="12" cy="10" r="2.75" />
      <path d="M6.4 18.6a6.3 6.3 0 0 1 11.2 0" />
    </svg>
  )
}

export function BellIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M18 10.5a6 6 0 1 0-12 0c0 3.4-.9 5-1.75 5.9-.4.42-.1 1.1.47 1.1h14.56c.57 0 .87-.68.47-1.1C18.9 15.5 18 13.9 18 10.5Z" />
      <path d="M9.75 17.5v.5a2.25 2.25 0 0 0 4.5 0v-.5" />
    </svg>
  )
}

export function SearchIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="10.75" cy="10.75" r="6" />
      <path d="m15.25 15.25 4.5 4.5" />
    </svg>
  )
}

export function PlusIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 5.25v13.5" />
      <path d="M5.25 12h13.5" />
    </svg>
  )
}

/** Opens the sidebar below lg, where the rail is a drawer. */
export function MenuIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </svg>
  )
}

export function CloseIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </svg>
  )
}

export function LogOutIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M9.75 20.25H6.5a1.75 1.75 0 0 1-1.75-1.75V5.5A1.75 1.75 0 0 1 6.5 3.75h3.25" />
      <path d="M15.5 8.25 19.25 12l-3.75 3.75" />
      <path d="M19.25 12H9.5" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Direction                                                                  */
/* -------------------------------------------------------------------------- */

/** Discloses a menu. Rotated by the caller when the menu is open. */
export function ChevronDownIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m6.75 9.75 5.25 5.25 5.25-5.25" />
    </svg>
  )
}

/** Leads somewhere. Used on rows and "View all" links, never on a menu. */
export function ChevronRightIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m9.75 6.75 5.25 5.25-5.25 5.25" />
    </svg>
  )
}

/** A rise, on a stat tile. Paired with green. */
export function ArrowUpIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 19.25v-14" />
      <path d="m6.75 10.5 5.25-5.25 5.25 5.25" />
    </svg>
  )
}

/** A fall. Paired with red — the tile has to be able to deliver bad news. */
export function ArrowDownIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 4.75v14" />
      <path d="m6.75 13.5 5.25 5.25 5.25-5.25" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Actions and content                                                        */
/* -------------------------------------------------------------------------- */

export function UploadIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 15.75v-11" />
      <path d="m7.75 9 4.25-4.25L16.25 9" />
      <path d="M4.75 15.25v2.5a2.5 2.5 0 0 0 2.5 2.5h9.5a2.5 2.5 0 0 0 2.5-2.5v-2.5" />
    </svg>
  )
}

/** Submits a prompt to the assistant. */
export function SendIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M20.25 3.75 3.75 10.5l6.25 2.5 2.5 6.25Z" />
      <path d="m10 13 4.25-4.25" />
    </svg>
  )
}

/** A query put to the assistant, and the count of them. */
export function ChatIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M20.25 11.9a7.6 7.6 0 0 1-7.6 7.6 7.9 7.9 0 0 1-3.35-.74L4.5 20.1l1.38-4.35a7.6 7.6 0 0 1 6.77-11.45 7.6 7.6 0 0 1 7.6 7.6Z" />
      <path d="M9.5 12h.1" />
      <path d="M12.5 12h.1" />
      <path d="M15.5 12h.1" />
    </svg>
  )
}

/** Something finished. The activity feed's "review completed" marker. */
export function CheckCircleIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="m8.25 12.25 2.6 2.6 5-5" />
    </svg>
  )
}

/** Stored bytes, for the storage meter. */
export function DatabaseIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <ellipse cx="12" cy="6.5" rx="7.25" ry="2.75" />
      <path d="M4.75 6.5v11c0 1.52 3.25 2.75 7.25 2.75s7.25-1.23 7.25-2.75v-11" />
      <path d="M4.75 12c0 1.52 3.25 2.75 7.25 2.75s7.25-1.23 7.25-2.75" />
    </svg>
  )
}

/**
 * Google's mark, in Google's colours. This one keeps its own fill values and
 * ignores currentColor: the brand guidelines require the four-colour G, and a
 * monochrome version of it would be recognisably wrong.
 */
export function GoogleIcon({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84Z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84c.87-2.6 3.3-4.51 6.16-4.51Z"
      />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Documents                                                                  */
/* -------------------------------------------------------------------------- */

/**
 * The arrow points down into a tray, which is the same tray Upload's arrow leaves.
 * Reversing one glyph rather than drawing two unrelated ones is what makes the pair
 * legible side by side in a row of actions.
 */
export function DownloadIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 3.75v10.5" />
      <path d="m7.75 10 4.25 4.25L16.25 10" />
      <path d="M4.75 16.25v1.5a2.5 2.5 0 0 0 2.5 2.5h9.5a2.5 2.5 0 0 0 2.5-2.5v-1.5" />
    </svg>
  )
}

/** Deleting a document. Destructive, so it is never the row's only affordance. */
export function TrashIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.75 7.25h14.5" />
      <path d="M9.5 7.25V5.5a1.25 1.25 0 0 1 1.25-1.25h2.5A1.25 1.25 0 0 1 14.5 5.5v1.75" />
      <path d="M6.75 7.25 7.6 18.4a1.75 1.75 0 0 0 1.75 1.6h5.3a1.75 1.75 0 0 0 1.75-1.6l.85-11.15" />
      <path d="M10.5 11v5.25" />
      <path d="M13.5 11v5.25" />
    </svg>
  )
}

/**
 * A funnel, for narrowing the table. Not the sliders used for Settings: that glyph
 * already means "preferences" in the sidebar, and one glyph carrying two meanings is
 * how a reader learns to stop trusting the set.
 */
export function FilterIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M4.25 5.75h15.5l-5.9 6.9v5.35l-3.7 1.85v-7.2Z" />
    </svg>
  )
}

/** Run it again — retrain a document, or refresh the listing. */
export function RefreshIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M19.25 12a7.25 7.25 0 1 1-2.4-5.4" />
      <path d="M19.25 4.75v3.5h-3.5" />
    </svg>
  )
}

/** Back a page in the viewer. The mirror of ChevronRight, same geometry. */
export function ChevronLeftIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M14.5 6.5 9 12l5.5 5.5" />
    </svg>
  )
}

/** Closer in. The plus inside the lens, so the pair differs by one stroke. */
export function ZoomInIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="10.75" cy="10.75" r="6" />
      <path d="m15.25 15.25 4 4" />
      <path d="M8.5 10.75h4.5" />
      <path d="M10.75 8.5v4.5" />
    </svg>
  )
}

/** Further out. */
export function ZoomOutIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="10.75" cy="10.75" r="6" />
      <path d="m15.25 15.25 4 4" />
      <path d="M8.5 10.75h4.5" />
    </svg>
  )
}

/** A keyword. The hole is what stops it reading as a plain arrow at 16px. */
export function TagIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12.6 4.25H19a.75.75 0 0 1 .75.75v6.4a1.75 1.75 0 0 1-.51 1.24l-6.35 6.35a1.75 1.75 0 0 1-2.48 0l-5.15-5.15a1.75 1.75 0 0 1 0-2.48l6.35-6.35a1.75 1.75 0 0 1 1.24-.51Z" />
      <path d="M16 8h.01" />
    </svg>
  )
}

/**
 * Something failed. The counterpart to CheckCircle, and the only one of the two that
 * gets an amber or rose treatment — never brand red, which means "VR-Nexus".
 */
export function XCircleIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="m9.25 9.25 5.5 5.5" />
      <path d="m14.75 9.25-5.5 5.5" />
    </svg>
  )
}

/** Chunks — one document split into stacked passages. */
export function LayersIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="m12 3.75 7.75 4-7.75 4-7.75-4Z" />
      <path d="m4.25 12.25 7.75 4 7.75-4" />
      <path d="m4.25 16.5 7.75 4 7.75-4" />
    </svg>
  )
}

/**
 * A sortable column that is not currently sorted. Both arrows, so the header reads
 * as "this can go either way" rather than claiming a direction it is not in — the
 * active column swaps this for ArrowUp or ArrowDown.
 */
export function ArrowUpDownIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M8.25 4.75v14.5" />
      <path d="m5.25 8 3-3.25L11.25 8" />
      <path d="M15.75 19.25V4.75" />
      <path d="m12.75 16 3 3.25L18.75 16" />
    </svg>
  )
}

/** A raster upload — png, jpg or tiff. The backend files all three as `image`. */
export function ImageIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="3.75" y="4.75" width="16.5" height="14.5" rx="2.5" />
      <circle cx="9" cy="10" r="1.5" />
      <path d="m4.25 17.5 4.6-4.6a1.75 1.75 0 0 1 2.48 0l5.42 5.42" />
      <path d="m14 15.25 1.6-1.6a1.75 1.75 0 0 1 2.48 0l2.17 2.17" />
    </svg>
  )
}

/** A deck — pptx. A framed slide on a stand, distinct from FileText's page. */
export function PresentationIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="3.75" y="4.25" width="16.5" height="10.5" rx="1.75" />
      <path d="M12 14.75v2.75" />
      <path d="m9 20.25 3-2.75 3 2.75" />
    </svg>
  )
}


export function SunIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  )
}

export function MoonIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* Tender Tools                                                               */
/* -------------------------------------------------------------------------- */

/** A clipboard with a tick, for the compliance matrix. */
export function ClipboardCheckIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M9 4.75H7.25A1.75 1.75 0 0 0 5.5 6.5v12a1.75 1.75 0 0 0 1.75 1.75h9.5a1.75 1.75 0 0 0 1.75-1.75V6.5a1.75 1.75 0 0 0-1.75-1.75H15" />
      <rect x="9" y="3.25" width="6" height="3" rx="1" />
      <path d="m9 13.5 2 2 4-4" />
    </svg>
  )
}

/** A calculator, for the evaluation score simulator. */
export function CalculatorIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <rect x="4.75" y="3.25" width="14.5" height="17.5" rx="2.25" />
      <rect x="7.5" y="6" width="9" height="4" rx="1" />
      <path d="M8.5 13.5h.01M12 13.5h.01M15.5 13.5h.01M8.5 16.5h.01M12 16.5h.01M15.5 16.5h.01" />
    </svg>
  )
}

/** A shield with an exclamation mark, for the risk scanner. */
export function ShieldAlertIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 3.25l7 2.55v5.9c0 4.2-2.9 7.55-7 8.95-4.1-1.4-7-4.75-7-8.95V5.8Z" />
      <path d="M12 9v3.5" />
      <path d="M12 15.25v.1" />
    </svg>
  )
}

/** A box with a checkmark, for the submission readiness checker. */
export function PackageCheckIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <path d="M12 3.75 20.25 8v8L12 20.25 3.75 16V8Z" />
      <path d="M3.75 8 12 12.25 20.25 8" />
      <path d="M12 12.25v8" />
    </svg>
  )
}

/** A circle with a question mark, for clarification questions. */
export function HelpCircleIcon({ className }: IconProps) {
  return (
    <svg {...strokeIcon} className={className}>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M9.75 9.75a2.25 2.25 0 0 1 4.35.75c0 1.5-2.1 2-2.1 3.25" />
      <path d="M12 16.25v.1" />
    </svg>
  )
}
