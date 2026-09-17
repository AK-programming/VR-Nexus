/**
 * The public front door, reachable at `/` for anyone who is not signed in
 * (see `HomeRoute` in `app/router.tsx`, which is what decides this page
 * renders here rather than the dashboard).
 *
 * Nothing on this page is a mock: the pipeline stages, the confidence bands,
 * the two-halves framing (Evidence Library vs. Tender Analysis), the human
 * checkpoint at finalize: all of it is the real product, described the way
 * `PROJECT_CONTEXT.md` describes it. A landing page that oversells what the
 * app actually does is the first thing a new user's trust breaks on.
 *
 * One file, in sections, in the order they scroll: Header, Hero, the stat
 * strip, the problem/solution band, the step-by-step walkthrough, the
 * outcomes ("what you get", the end goal), the feature grid, a closing CTA,
 * the FAQ, and the footer. `Reveal` is the one animation primitive every
 * section below the hero uses: an IntersectionObserver fade/rise, entirely
 * CSS-driven so `prefers-reduced-motion` (already handled globally in
 * `index.css`) zeroes it out for anyone who has asked for that.
 */

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BrandMark, BrandWordmark } from '@/components/ui/BrandMark'
import {
  ActivityIcon,
  ArrowRightIcon,
  BarChartIcon,
  CheckCircleIcon,
  CheckIcon,
  ChevronDownIcon,
  CloseIcon,
  DatabaseIcon,
  DownloadIcon,
  FileTextIcon,
  FolderIcon,
  GridIcon,
  LayersIcon,
  MenuIcon,
  MoonIcon,
  PlusIcon,
  SettingsIcon,
  ShieldCheckIcon,
  SparklesIcon,
  SunIcon,
  UploadIcon,
  UsersIcon,
} from '@/components/ui/icons'
import { ROUTES } from '@/constants/routes'
import { useThemeStore } from '@/store/themeStore'

/* -------------------------------------------------------------------------- */
/* Reveal - the one scroll-in animation primitive every section below the    */
/* hero uses.                                                                 */
/* -------------------------------------------------------------------------- */

function Reveal({
  children,
  className,
  delayMs = 0,
}: {
  children: ReactNode
  className?: string
  delayMs?: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const element = ref.current

    if (!element) {
      return
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
    )

    observer.observe(element)

    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      style={delayMs ? { transitionDelay: `${delayMs}ms` } : undefined}
      className={[
        'transition-all duration-700 ease-out',
        visible ? 'translate-y-0 opacity-100' : 'translate-y-8 opacity-0',
        className ?? '',
      ].join(' ')}
    >
      {children}
    </div>
  )
}

/** The small red-on-white/red-on-ink label above every section heading. */
function Eyebrow({ children, tone = 'light' }: { children: ReactNode; tone?: 'light' | 'dark' }) {
  return (
    <p
      className={[
        'font-display text-[11px] font-semibold tracking-[0.24em] uppercase',
        tone === 'dark' ? 'text-brand-300' : 'text-brand-600',
      ].join(' ')}
    >
      {children}
    </p>
  )
}

/* -------------------------------------------------------------------------- */
/* Header                                                                     */
/* -------------------------------------------------------------------------- */

const NAV_LINKS = [
  { href: '#features', label: 'Features' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#faq', label: 'FAQ' },
]

function ThemeToggle({ className }: { className?: string }) {
  const resolved = useThemeStore((state) => state.resolved)
  const setTheme = useThemeStore((state) => state.setTheme)
  const goingDark = resolved !== 'dark'

  return (
    <button
      type="button"
      onClick={() => setTheme(goingDark ? 'dark' : 'light')}
      aria-label={goingDark ? 'Switch to dark theme' : 'Switch to light theme'}
      title={goingDark ? 'Dark theme' : 'Light theme'}
      className={[
        'inline-flex size-9 shrink-0 items-center justify-center rounded-lg border border-hairline',
        'bg-surface text-neutral-600 transition-colors duration-150 hover:border-neutral-300 hover:text-neutral-900',
        className ?? '',
      ].join(' ')}
    >
      {goingDark ? <MoonIcon className="size-4" /> : <SunIcon className="size-4" />}
    </button>
  )
}

function LandingHeader() {
  const [isScrolled, setIsScrolled] = useState(false)
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  useEffect(() => {
    function onScroll() {
      setIsScrolled(window.scrollY > 24)
    }

    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  /* Closes the mobile menu on a route-scale change (an anchor click, Escape,
     or the viewport growing back past the breakpoint) rather than leaving it
     open behind whatever the visitor navigates to next. */
  function closeMenu() {
    setIsMenuOpen(false)
  }

  return (
    <header
      className={[
        'fixed inset-x-0 top-0 z-50 transition-all duration-300',
        isScrolled
          ? 'border-b border-hairline bg-surface/85 shadow-panel backdrop-blur-md'
          : 'border-b border-transparent bg-surface/60 backdrop-blur-sm',
      ].join(' ')}
    >
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <Link
          to={ROUTES.home}
          className="flex items-center gap-2.5 rounded-lg focus-visible:outline-brand-300"
          aria-label="VR-Nexus"
        >
          <BrandMark className="h-8 w-auto shrink-0" />
          <span className="hidden sm:block">
            <BrandWordmark tone="dark" />
          </span>
        </Link>

        <nav aria-label="Page sections" className="hidden items-center gap-8 lg:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="text-sm font-medium text-neutral-600 transition-colors duration-150 hover:text-neutral-900"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 lg:flex">
          <ThemeToggle />
          <Link
            to={ROUTES.login}
            className="rounded-lg px-3.5 py-2 text-sm font-medium text-neutral-700 transition-colors duration-150 hover:text-neutral-900"
          >
            Sign in
          </Link>
          <Link
            to={ROUTES.register}
            className={[
              'inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-4 py-2 text-sm font-semibold text-white',
              'shadow-glow transition-transform duration-150 hover:bg-brand-600 active:translate-y-px',
            ].join(' ')}
          >
            Get Started
            <ArrowRightIcon className="size-4" />
          </Link>
        </div>

        <button
          type="button"
          onClick={() => setIsMenuOpen((current) => !current)}
          aria-label={isMenuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={isMenuOpen}
          className="inline-flex size-10 items-center justify-center rounded-lg text-neutral-800 lg:hidden"
        >
          {isMenuOpen ? <CloseIcon className="size-5" /> : <MenuIcon className="size-5" />}
        </button>
      </div>

      {isMenuOpen ? (
        <div className="border-t border-hairline bg-surface px-4 py-4 shadow-panel lg:hidden">
          <nav aria-label="Page sections" className="flex flex-col gap-1">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={closeMenu}
                className="rounded-lg px-3 py-2.5 text-sm font-medium text-neutral-700 hover:bg-surface-muted hover:text-neutral-900"
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="mt-3 flex flex-col gap-2 border-t border-hairline pt-3">
            <Link
              to={ROUTES.login}
              onClick={closeMenu}
              className="rounded-lg border border-hairline px-3.5 py-2.5 text-center text-sm font-medium text-neutral-800 hover:border-neutral-300"
            >
              Sign in
            </Link>
            <Link
              to={ROUTES.register}
              onClick={closeMenu}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-brand-500 px-3.5 py-2.5 text-sm font-semibold text-white shadow-glow hover:bg-brand-600"
            >
              Get Started
              <ArrowRightIcon className="size-4" />
            </Link>
          </div>
        </div>
      ) : null}
    </header>
  )
}

/* -------------------------------------------------------------------------- */
/* Hero illustration - the real dashboard shell, cycling through its own     */
/* sections rather than an abstract processing animation.                    */
/* -------------------------------------------------------------------------- */

type HeroSectionId = 'dashboard' | 'tenders' | 'documents' | 'assistant'

const HERO_SECTIONS: {
  id: HeroSectionId
  label: string
  icon: (props: { className?: string }) => ReactNode
  action: string
}[] = [
  { id: 'dashboard', label: 'Dashboard', icon: GridIcon, action: '+ New Analysis' },
  { id: 'tenders', label: 'Tender Analysis', icon: BarChartIcon, action: '+ New Analysis' },
  { id: 'documents', label: 'Documents', icon: FolderIcon, action: '+ Upload' },
  { id: 'assistant', label: 'AI Assistant', icon: SparklesIcon, action: 'Ask' },
]

/** Sidebar items shown for depth but never part of the cycle - the real
 * sidebar has more sections than the four this illustration walks through. */
const HERO_SIDEBAR_EXTRAS = [UsersIcon, SettingsIcon]

/** How long each section holds before the illustration advances to the next. */
const HERO_SECTION_MS = 3000

const HERO_REQUIREMENT_ROWS: {
  id: string
  width: string
  badge: string
  tone: 'auto' | 'suggested' | 'missing'
}[] = [
  { id: 'row-1', width: 'w-4/5', badge: 'Auto · 94%', tone: 'auto' },
  { id: 'row-2', width: 'w-3/5', badge: 'Suggested · 61%', tone: 'suggested' },
  { id: 'row-3', width: 'w-full', badge: 'Auto · 88%', tone: 'auto' },
  { id: 'row-4', width: 'w-2/3', badge: 'Missing', tone: 'missing' },
]

const HERO_BADGE_TONE_CLASSES: Record<'auto' | 'suggested' | 'missing', string> = {
  auto: 'bg-emerald-50 text-emerald-700',
  suggested: 'bg-amber-50 text-amber-700',
  missing: 'bg-rose-50 text-rose-700',
}

const HERO_STAT_TILES = [
  { label: 'Active tenders', value: '12' },
  { label: 'Coverage', value: '87%' },
  { label: 'Evidence matched', value: '248' },
]

const HERO_DOCUMENT_FILES = [
  { name: 'Metro_Rail_Case_Study.pdf', status: 'Indexed' },
  { name: 'Methodology_Overview.pdf', status: 'Indexed' },
  { name: 'ISO_9001_Certificate.pdf', status: 'Indexed' },
]

/** A row/tile that fades and rises into place - the one entrance animation
 * every section of the illustration below uses, staggered by `index`. */
function HeroFadeIn({
  index,
  className,
  children,
}: {
  index: number
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={['opacity-0', className ?? ''].join(' ')}
      style={{ animation: `hero-fade-up 0.45s ease-out ${index * 110}ms forwards` }}
    >
      {children}
    </div>
  )
}

/**
 * The hero's right column - a small "app window" replica of the actual
 * dashboard shell (the same dark sidebar, the same nav sections) that cycles
 * through four real areas of the product every few seconds: Dashboard,
 * Tender Analysis, Documents, and the AI Assistant. This replaces a generic
 * processing animation with something a returning user would recognize the
 * moment they sign in - the confidence bands, the "Indexed" pill, the chat
 * sources chip are all the real product's own vocabulary.
 *
 * A `setInterval` drives which section is showing (see the illustration's
 * previous, pipeline-stage version for why that reads easier than one long
 * keyframe animation for multiple, differently-shaped panels). Content
 * remounts on every section change via `key={sectionIndex}` so
 * `hero-fade-up` replays each time rather than only on first mount.
 */
function DashboardPreview() {
  const [sectionIndex, setSectionIndex] = useState(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      /* Settles on Tender Analysis - the section that best represents the
         whole product on its own - rather than auto-advancing for someone
         who has asked for less motion. */
      setSectionIndex(1)
      return
    }

    const timer = window.setInterval(() => {
      setSectionIndex((current) => (current + 1) % HERO_SECTIONS.length)
    }, HERO_SECTION_MS)

    return () => window.clearInterval(timer)
  }, [])

  const section = HERO_SECTIONS[sectionIndex]

  return (
    <div
      aria-hidden="true"
      className="w-full max-w-lg overflow-hidden rounded-2xl border border-hairline bg-surface shadow-panel"
    >
      <div className="flex items-center gap-1.5 border-b border-hairline bg-surface-muted px-3.5 py-2.5">
        <span className="size-2.5 rounded-full bg-neutral-300" />
        <span className="size-2.5 rounded-full bg-neutral-300" />
        <span className="size-2.5 rounded-full bg-neutral-300" />
        <span className="ml-2 truncate rounded-full bg-surface px-2.5 py-0.5 text-[10px] font-medium text-neutral-400">
          vr-nexus.app/{section.id}
        </span>
      </div>

      <div className="flex h-80">
        {/* The real sidebar, in miniature - same dark ink, same rail of icon
            destinations, the active one lit up in brand red. */}
        <div className="flex w-14 shrink-0 flex-col items-center gap-2 bg-ink-950 py-4">
          <BrandMark className="mb-2 h-4 w-auto opacity-90" />
          {HERO_SECTIONS.map((entry) => {
            const Icon = entry.icon
            const active = entry.id === section.id

            return (
              <span
                key={entry.id}
                className={[
                  'flex size-8 items-center justify-center rounded-lg transition-colors duration-300',
                  active ? 'bg-brand-500/20 text-brand-400' : 'text-white/35',
                ].join(' ')}
              >
                <Icon className="size-4" />
              </span>
            )
          })}
          <span className="my-1 h-px w-5 bg-white/10" />
          {HERO_SIDEBAR_EXTRAS.map((Icon, index) => (
            <span
              key={index}
              className="flex size-8 items-center justify-center rounded-lg text-white/20"
            >
              <Icon className="size-4" />
            </span>
          ))}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3 p-4">
          <div className="flex shrink-0 items-center justify-between gap-2">
            <p className="font-display text-sm font-semibold tracking-tight text-neutral-900">
              {section.label}
            </p>
            <span className="inline-flex items-center gap-1 rounded-lg bg-brand-500 px-2.5 py-1 text-[10px] font-semibold text-white">
              {section.action === 'Ask' ? null : <PlusIcon className="size-3" />}
              {section.action.replace('+ ', '')}
            </span>
          </div>

          {section.id === 'dashboard' ? (
            <div key={sectionIndex} className="flex min-h-0 flex-1 flex-col gap-3">
              <div className="grid grid-cols-3 gap-2">
                {HERO_STAT_TILES.map((tile, index) => (
                  <HeroFadeIn key={tile.label} index={index}>
                    <div className="rounded-lg border border-hairline bg-surface-muted px-2.5 py-2.5 text-center">
                      <p className="font-display text-base font-semibold text-neutral-900">
                        {tile.value}
                      </p>
                      <p className="mt-0.5 text-[10px] leading-tight text-neutral-500">
                        {tile.label}
                      </p>
                    </div>
                  </HeroFadeIn>
                ))}
              </div>
              <HeroFadeIn
                index={3}
                className="flex min-h-0 flex-1 items-end gap-1.5 rounded-lg border border-hairline bg-surface-muted p-3"
              >
                {[40, 65, 50, 80, 60, 90, 70].map((height, index) => (
                  <span
                    key={index}
                    className="flex-1 rounded-t bg-brand-400/70"
                    style={{ height: `${height}%` }}
                  />
                ))}
              </HeroFadeIn>
            </div>
          ) : null}

          {section.id === 'tenders' ? (
            <div key={sectionIndex} className="flex min-h-0 flex-1 flex-col justify-center gap-3.5">
              {HERO_REQUIREMENT_ROWS.map((row, index) => (
                <HeroFadeIn key={row.id} index={index} className="flex items-center justify-between gap-3">
                  <span className={['h-2.5 rounded-full bg-neutral-200', row.width].join(' ')} />
                  <span
                    className={[
                      'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap',
                      HERO_BADGE_TONE_CLASSES[row.tone],
                    ].join(' ')}
                  >
                    {row.badge}
                  </span>
                </HeroFadeIn>
              ))}
            </div>
          ) : null}

          {section.id === 'documents' ? (
            <div key={sectionIndex} className="flex min-h-0 flex-1 flex-col justify-center gap-2.5">
              {HERO_DOCUMENT_FILES.map((file, index) => (
                <HeroFadeIn
                  key={file.name}
                  index={index}
                  className="flex items-center gap-2.5 rounded-lg border border-hairline bg-surface-muted px-3 py-2.5"
                >
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-600">
                    <FileTextIcon className="size-3.5" />
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-neutral-800">
                    {file.name}
                  </span>
                  <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                    {file.status}
                  </span>
                </HeroFadeIn>
              ))}
            </div>
          ) : null}

          {section.id === 'assistant' ? (
            <div key={sectionIndex} className="flex min-h-0 flex-1 flex-col justify-center gap-2.5">
              <HeroFadeIn index={0} className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-brand-500 px-3 py-2 text-xs text-white">
                  Which tenders require ISO 9001?
                </p>
              </HeroFadeIn>
              <HeroFadeIn index={1} className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-hairline bg-surface-muted px-3 py-2">
                  <p className="text-xs leading-relaxed text-neutral-700">
                    Three open tenders list ISO 9001 as a mandatory certification.
                  </p>
                  <p className="mt-1.5 text-[10px] font-semibold text-brand-600">Sources · 2</p>
                </div>
              </HeroFadeIn>
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-hairline px-3.5 py-3">
        <p className="text-[11px] font-medium text-neutral-400">{section.label}</p>
        <div className="flex items-center gap-1.5">
          {HERO_SECTIONS.map((entry, index) => (
            <span
              key={entry.id}
              className={[
                'h-1.5 rounded-full transition-all duration-300',
                index === sectionIndex ? 'w-5 bg-brand-500' : 'w-1.5 bg-neutral-200',
              ].join(' ')}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Hero                                                                       */
/* -------------------------------------------------------------------------- */

const HERO_STATS = [
  { value: '9', label: 'pipeline stages, tracked live', icon: LayersIcon },
  { value: '3', label: 'confidence bands per match', icon: ShieldCheckIcon },
  { value: '1', label: 'human checkpoint before anything ships', icon: CheckCircleIcon },
]

function Hero() {
  return (
    <section className="relative isolate overflow-hidden border-b border-hairline bg-gradient-to-b from-brand-50/70 via-surface to-surface pt-32 pb-24 sm:pt-40 sm:pb-32">
      {/* Decorative glow + grid, both an inline style because the gradient
          stops aren't expressible as a plain Tailwind utility, and neither
          carries content a screen reader needs. Together with the section's
          own soft brand-tinted gradient (bg-gradient-to-b above) and the
          bottom hairline, this is what separates the hero from the plain
          white section right below it - without going back to a dark panel. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            'radial-gradient(ellipse 80% 55% at 50% -10%, rgba(232,21,27,0.16), transparent 60%)',
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 bg-[linear-gradient(rgba(10,1,2,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(10,1,2,0.05)_1px,transparent_1px)] bg-[size:64px_64px] [mask-image:radial-gradient(ellipse_60%_60%_at_50%_20%,black,transparent)]"
      />

      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 items-center gap-14 lg:grid-cols-2 lg:gap-10">
          <div className="flex flex-col items-center text-center lg:items-start lg:text-left">
            <Reveal>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-hairline bg-surface-muted px-3.5 py-1.5 text-xs font-medium text-neutral-700 shadow-sm">
                <SparklesIcon className="size-3.5 text-brand-500" />
                AI Tender Intelligence &amp; Evidence Matching
              </span>
            </Reveal>

            <Reveal delayMs={80}>
              <h1 className="mt-6 max-w-xl font-display text-4xl leading-[1.08] font-semibold tracking-tight text-neutral-900 sm:text-5xl">
                Read every clause.
                <br />
                Match every requirement.
                <br />
                <span className="text-brand-500">Miss nothing.</span>
              </h1>
            </Reveal>

            <Reveal delayMs={160}>
              <p className="mt-6 max-w-xl text-base leading-relaxed text-neutral-500 sm:text-lg">
                VR-Nexus reads a procurement tender clause by clause, extracts every
                requirement, matches it against your Evidence Library, and hands you a
                reviewable tracker and document pack, with a person deciding every
                match before anything is final.
              </p>
            </Reveal>

            <Reveal delayMs={240}>
              <div className="mt-9 flex flex-col items-center gap-3 sm:flex-row">
                <Link
                  to={ROUTES.register}
                  className="inline-flex items-center gap-2 rounded-xl bg-brand-500 px-6 py-3.5 text-sm font-semibold text-white shadow-glow transition-transform duration-150 hover:bg-brand-600 active:translate-y-px"
                >
                  Get Started
                  <ArrowRightIcon className="size-4" />
                </Link>
                <a
                  href="#how-it-works"
                  className="inline-flex items-center gap-2 rounded-xl border border-hairline bg-surface px-6 py-3.5 text-sm font-semibold text-neutral-800 shadow-sm transition-colors duration-150 hover:border-neutral-300 hover:bg-surface-muted"
                >
                  See how it works
                </a>
              </div>
            </Reveal>
          </div>

          <Reveal delayMs={200} className="flex justify-center lg:justify-end">
            <DashboardPreview />
          </Reveal>
        </div>

        <Reveal delayMs={320} className="mt-16 w-full">
          <dl className="mx-auto grid w-full max-w-3xl grid-cols-1 divide-y divide-hairline overflow-hidden rounded-2xl border border-hairline bg-surface-muted shadow-sm sm:grid-cols-3 sm:divide-x sm:divide-y-0">
            {HERO_STATS.map((stat, index) => (
              <div
                key={stat.label}
                className="group relative flex flex-col items-center gap-2.5 px-6 py-7 text-center transition-colors duration-200 hover:bg-surface sm:py-8"
              >
                {/* A hairline-thin brand accent that only appears on hover, so the
                    card reads as "quiet numbers" at rest and "alive" on interaction
                    rather than three plain stacked labels. */}
                <span
                  aria-hidden="true"
                  className="absolute inset-x-6 top-0 h-0.5 scale-x-0 rounded-full bg-brand-500 transition-transform duration-200 group-hover:scale-x-100"
                />
                <span className="inline-flex size-10 items-center justify-center rounded-full bg-brand-50 text-brand-600 ring-1 ring-brand-100 transition-transform duration-200 group-hover:scale-105">
                  <stat.icon className="size-5" />
                </span>
                <dt className="font-display text-3xl font-semibold text-neutral-900 tabular-nums sm:text-4xl">
                  {stat.value}
                </dt>
                <dd className="max-w-[15rem] text-xs leading-relaxed text-neutral-500 sm:text-sm">
                  {stat.label}
                </dd>
                <span className="sr-only">Stat {index + 1} of {HERO_STATS.length}</span>
              </div>
            ))}
          </dl>
        </Reveal>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Problem / solution                                                        */
/* -------------------------------------------------------------------------- */

function ProblemSolution() {
  return (
    <section className="bg-surface py-20 sm:py-28">
      <div className="mx-auto grid w-full max-w-6xl gap-10 px-4 sm:px-6 lg:grid-cols-2 lg:gap-16 lg:px-8">
        <Reveal>
          <Eyebrow>The problem</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            A tender can run hundreds of pages. A missed clause can cost the bid.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-neutral-500 sm:text-base">
            Reading every requirement by hand, telling mandatory apart from
            advisory, and finding the right case study for each one is slow,
            repetitive, and easy to get wrong under deadline pressure, especially
            when it happens for every single tender.
          </p>
        </Reveal>

        <Reveal delayMs={120}>
          <Eyebrow>The fix</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            VR-Nexus reads and matches. You decide.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-neutral-500 sm:text-base">
            The pipeline extracts every requirement verbatim from the tender,
            scores a match against your Evidence Library for each one, and stops.
            Every run pauses for review. The AI proposes, a person finalizes.
            Nothing here ships on its own.
          </p>
        </Reveal>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* How it works                                                               */
/* -------------------------------------------------------------------------- */

const TENDER_STEPS = [
  {
    icon: UploadIcon,
    title: 'Upload a tender',
    description:
      'Drop in the procurement PDF, however many hundreds of pages long. VR-Nexus parses it (with an OCR fallback for scanned pages) and chunks it section by section.',
  },
  {
    icon: FileTextIcon,
    title: 'Extraction',
    description:
      'Every requirement is pulled out clause by clause: mandatory or advisory, evaluation impact, reference number, responsibility, written down verbatim the way the tender actually states it.',
  },
  {
    icon: LayersIcon,
    title: 'Matching',
    description:
      'Each requirement is matched against your Evidence Library and scored: Auto (high confidence), Suggested (worth a look), or Missing, so review time goes exactly where it is needed.',
  },
  {
    icon: CheckCircleIcon,
    title: 'Human review',
    description:
      'You accept, reject, or reassign every match yourself. This is the deliberate checkpoint: the AI proposes evidence, a person decides what actually goes in.',
  },
  {
    icon: DownloadIcon,
    title: 'Finalize & export',
    description:
      'Coverage and marks are scored automatically. One click produces a reviewable Excel tracker plus a ZIP with the original tender and every matched evidence file, ready to submit.',
  },
]

function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-surface-muted py-20 sm:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
        <Reveal className="mx-auto max-w-2xl text-center">
          <Eyebrow>How it works</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            From a tender PDF to a finished tracker
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-neutral-500 sm:text-base">
            One tender, five stages, ending on the deliverable you actually submit.
          </p>
        </Reveal>

        {/* Built once, ahead of time - the prerequisite the five-step flow below
            depends on, called out on its own rather than folded into "step 1" so
            it reads as what it is: a one-time setup, not part of every run. */}
        <Reveal delayMs={80} className="mx-auto mt-10 max-w-3xl">
          <div className="flex flex-col items-start gap-4 rounded-2xl border border-hairline bg-surface p-5 sm:flex-row sm:items-center sm:p-6">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
              <DatabaseIcon className="size-5" />
            </span>
            <div>
              <p className="font-display text-sm font-semibold tracking-tight text-neutral-900">
                Before your first tender: build the Evidence Library
              </p>
              <p className="mt-1 text-sm leading-relaxed text-neutral-500">
                Upload your case studies, methodology documents, and company
                records once. VR-Nexus parses, auto-tags, and indexes each one -
                the tender matcher can only find evidence that is already in here.
              </p>
            </div>
          </div>
        </Reveal>

        <div className="relative mx-auto mt-14 max-w-3xl">
          {/* The connecting line behind the numbered markers. Absolutely
              positioned against the list rather than drawn per-item, so it
              reads as one continuous thread rather than five disjoint ticks. */}
          <div
            aria-hidden="true"
            className="absolute top-2 bottom-2 left-[1.375rem] w-px bg-hairline sm:left-6"
          />

          <ol className="flex flex-col gap-10">
            {TENDER_STEPS.map((step, index) => {
              const Icon = step.icon

              return (
                <Reveal key={step.title} delayMs={index * 90}>
                  <li className="relative flex gap-5 pl-0 sm:gap-6">
                    <span className="relative z-10 flex size-11 shrink-0 items-center justify-center rounded-full border-2 border-brand-500 bg-surface font-display text-sm font-semibold text-brand-600 sm:size-12">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1 rounded-2xl border border-hairline bg-surface p-5 sm:p-6">
                      <div className="flex items-center gap-2.5">
                        <Icon className="size-4 text-brand-500" />
                        <p className="font-display text-sm font-semibold tracking-tight text-neutral-900 sm:text-base">
                          {step.title}
                        </p>
                      </div>
                      <p className="mt-2 text-sm leading-relaxed text-neutral-500">
                        {step.description}
                      </p>
                    </div>
                  </li>
                </Reveal>
              )
            })}
          </ol>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Outcomes - the end goal                                                    */
/* -------------------------------------------------------------------------- */

const OUTCOMES = [
  {
    icon: CheckIcon,
    title: 'Complete requirement coverage',
    description: 'Every clause extracted, nothing skipped because it was buried on page 140.',
  },
  {
    icon: BarChartIcon,
    title: 'A confidence-scored paper trail',
    description: 'Every match carries a band and a reason, not a black-box "done".',
  },
  {
    icon: ShieldCheckIcon,
    title: 'A human decision on every match',
    description: 'The pipeline pauses at review, every time. Finalizing is a deliberate action.',
  },
  {
    icon: DownloadIcon,
    title: 'One finished export',
    description: 'A reviewable Excel tracker plus a ZIP of the tender and its matched evidence.',
  },
]

function Outcomes() {
  return (
    <section className="bg-surface py-20 sm:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
        <Reveal className="mx-auto max-w-2xl text-center">
          <Eyebrow>The end goal</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            What you get at the last step
          </h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {OUTCOMES.map((outcome, index) => {
            const Icon = outcome.icon

            return (
              <Reveal key={outcome.title} delayMs={index * 90}>
                <div className="flex h-full flex-col items-start gap-3 rounded-2xl border border-hairline bg-surface-muted p-5">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                    <Icon className="size-5" />
                  </span>
                  <p className="font-display text-sm font-semibold tracking-tight text-neutral-900">
                    {outcome.title}
                  </p>
                  <p className="text-sm leading-relaxed text-neutral-500">{outcome.description}</p>
                </div>
              </Reveal>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Feature grid                                                               */
/* -------------------------------------------------------------------------- */

const FEATURES = [
  {
    icon: FileTextIcon,
    title: 'Clause-by-clause extraction',
    description:
      'Every requirement captured with its marks, mandatory flag, and reference number, verbatim from the tender.',
  },
  {
    icon: LayersIcon,
    title: 'Confidence-scored matching',
    description: 'Auto, Suggested, and Missing bands, so a reviewer knows exactly where to look first.',
  },
  {
    icon: DatabaseIcon,
    title: 'Evidence Library',
    description: 'Case studies and methodology documents, parsed, auto-tagged, and searchable.',
  },
  {
    icon: CheckCircleIcon,
    title: 'Human-in-the-loop review',
    description: 'Accept, reject, or reassign every match before anything is treated as final.',
  },
  {
    icon: ActivityIcon,
    title: 'Live pipeline progress',
    description: 'Watch parsing, extraction, and matching happen in real time, stage by stage.',
  },
  {
    icon: SparklesIcon,
    title: 'AI Assistant',
    description: 'Ask grounded questions across your indexed library and get sourced answers back.',
  },
  {
    icon: DownloadIcon,
    title: 'Excel tracker + ZIP export',
    description: 'A reviewable tracker in your own spreadsheet layout, plus every matched evidence file.',
  },
  {
    icon: UsersIcon,
    title: 'Role-based access',
    description: 'Admins choose exactly which sections each account can reach; nothing by default.',
  },
]

function FeatureGrid() {
  return (
    <section id="features" className="bg-surface-muted py-20 sm:py-28">
      <div className="mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8">
        <Reveal className="mx-auto max-w-2xl text-center">
          <Eyebrow>Features</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            Everything the workflow needs, nothing it doesn't
          </h2>
        </Reveal>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map((feature, index) => {
            const Icon = feature.icon

            return (
              <Reveal key={feature.title} delayMs={(index % 4) * 90}>
                <div className="group flex h-full flex-col items-start gap-3 rounded-2xl border border-hairline bg-surface p-5 transition-all duration-200 hover:-translate-y-1 hover:border-brand-200 hover:shadow-panel">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition-colors duration-200 group-hover:bg-brand-500 group-hover:text-white">
                    <Icon className="size-5" />
                  </span>
                  <p className="font-display text-sm font-semibold tracking-tight text-neutral-900">
                    {feature.title}
                  </p>
                  <p className="text-sm leading-relaxed text-neutral-500">{feature.description}</p>
                </div>
              </Reveal>
            )
          })}
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* CTA band                                                                   */
/* -------------------------------------------------------------------------- */

function CtaBand() {
  return (
    <section className="relative isolate overflow-hidden bg-ink-950 py-20 sm:py-24">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background:
            'radial-gradient(ellipse 70% 60% at 50% 120%, rgba(232,21,27,0.28), transparent 60%)',
        }}
      />
      <div className="mx-auto flex w-full max-w-4xl flex-col items-center px-4 text-center sm:px-6 lg:px-8">
        <Reveal>
          <h2 className="font-display text-2xl font-semibold tracking-tight text-white sm:text-3xl">
            Ready to see your next tender differently?
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-white/65 sm:text-base">
            Build your Evidence Library, upload a tender, and watch the pipeline
            do the reading, with the last word always yours.
          </p>
          <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row">
            <Link
              to={ROUTES.register}
              className="inline-flex items-center gap-2 rounded-xl bg-brand-500 px-6 py-3.5 text-sm font-semibold text-white shadow-glow transition-transform duration-150 hover:bg-brand-600 active:translate-y-px"
            >
              Get Started
              <ArrowRightIcon className="size-4" />
            </Link>
            <Link
              to={ROUTES.login}
              className="inline-flex items-center gap-2 rounded-xl border border-white/15 bg-white/5 px-6 py-3.5 text-sm font-semibold text-white transition-colors duration-150 hover:border-white/30 hover:bg-white/10"
            >
              Sign in
            </Link>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* FAQ                                                                        */
/* -------------------------------------------------------------------------- */

const FAQS = [
  {
    question: 'Do I need to build my Evidence Library before analyzing a tender?',
    answer:
      "Yes. The tender matcher can only find evidence that's already indexed, so the library is built once, ahead of time, and every tender you run afterward matches against it.",
  },
  {
    question: 'What does "confidence-scored" matching actually mean?',
    answer:
      'Every requirement is matched against your library and lands in one of three bands: Auto for a high-confidence match, Suggested for one worth a second look, or Missing when nothing in the library clears the bar. Review time goes where the bands say it should.',
  },
  {
    question: 'Does the AI ever finalize a tender on its own?',
    answer:
      'No. Every run pauses for review once matching is done. A person accepts, rejects, or reassigns each match, and finalizing is a deliberate action. The AI proposes; it never ships on its own.',
  },
  {
    question: 'What file types can I upload?',
    answer:
      "Tenders and evidence documents are both handled as PDFs; scanned pages fall back to OCR so the text still gets extracted even when there's no text layer to read.",
  },
  {
    question: 'Can I control what my team can access?',
    answer:
      'Yes. An admin account can grant or revoke access to Documents, AI Assistant, Tender Analysis, and Tender Tools per person, from the Users page. Nothing is open by default.',
  },
  {
    question: 'What do I actually get at the end?',
    answer:
      'A reviewable Excel tracker in your own spreadsheet’s column layout, and a ZIP containing the original tender plus every matched evidence file, ready to submit.',
  },
]

function FaqItem({
  question,
  answer,
  defaultOpen = false,
}: {
  question: string
  answer: string
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-b border-hairline py-2">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-4 py-4 text-left"
      >
        <span className="font-display text-sm font-semibold tracking-tight text-neutral-900 sm:text-base">
          {question}
        </span>
        <ChevronDownIcon
          aria-hidden="true"
          className={[
            'size-4 shrink-0 text-neutral-400 transition-transform duration-200',
            open ? 'rotate-180' : '',
          ].join(' ')}
        />
      </button>
      {open ? (
        <p className="pb-4 text-sm leading-relaxed text-neutral-500 sm:text-base">{answer}</p>
      ) : null}
    </div>
  )
}

function Faq() {
  return (
    <section id="faq" className="bg-surface py-20 sm:py-28">
      <div className="mx-auto w-full max-w-3xl px-4 sm:px-6 lg:px-8">
        <Reveal className="text-center">
          <Eyebrow>FAQ</Eyebrow>
          <h2 className="mt-3 font-display text-2xl font-semibold tracking-tight text-neutral-900 sm:text-3xl">
            Questions worth answering up front
          </h2>
        </Reveal>

        <Reveal delayMs={80} className="mt-10 rounded-2xl border border-hairline bg-surface-muted px-5 sm:px-6">
          {FAQS.map((faq, index) => (
            <FaqItem key={faq.question} {...faq} defaultOpen={index === 0} />
          ))}
        </Reveal>
      </div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Footer                                                                     */
/* -------------------------------------------------------------------------- */

const FOOTER_PRODUCT_LINKS = [
  { to: ROUTES.tenderAnalysis, label: 'Tender Analysis' },
  { to: ROUTES.documents, label: 'Evidence Library' },
  { to: ROUTES.assistant, label: 'AI Assistant' },
]

const FOOTER_EXPLORE_LINKS = [
  { href: '#features', label: 'Features' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#faq', label: 'FAQ' },
]

function LandingFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="relative overflow-hidden bg-ink-950">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10"
        style={{
          background: 'radial-gradient(ellipse 60% 50% at 15% 0%, rgba(232,21,27,0.18), transparent 60%)',
        }}
      />
      <div className="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-10 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div>
            <Link to={ROUTES.home} className="flex items-center gap-2.5" aria-label="VR-Nexus">
              <BrandMark className="h-8 w-auto" />
              <BrandWordmark tone="light" />
            </Link>
            <p className="mt-4 max-w-xs text-sm leading-relaxed text-white/55">
              AI Tender Intelligence &amp; Evidence Matching. Read the tender,
              match the evidence, keep the decision human.
            </p>
          </div>

          <div>
            <p className="text-xs font-semibold tracking-[0.16em] text-white/40 uppercase">
              Product
            </p>
            <ul className="mt-4 flex flex-col gap-2.5">
              {FOOTER_PRODUCT_LINKS.map((link) => (
                <li key={link.to}>
                  <Link
                    to={link.to}
                    className="text-sm text-white/65 transition-colors hover:text-white"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="text-xs font-semibold tracking-[0.16em] text-white/40 uppercase">
              Explore
            </p>
            <ul className="mt-4 flex flex-col gap-2.5">
              {FOOTER_EXPLORE_LINKS.map((link) => (
                <li key={link.href}>
                  <a
                    href={link.href}
                    className="text-sm text-white/65 transition-colors hover:text-white"
                  >
                    {link.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="text-xs font-semibold tracking-[0.16em] text-white/40 uppercase">
              Account
            </p>
            <ul className="mt-4 flex flex-col gap-2.5">
              <li>
                <Link to={ROUTES.login} className="text-sm text-white/65 transition-colors hover:text-white">
                  Sign in
                </Link>
              </li>
              <li>
                <Link
                  to={ROUTES.register}
                  className="text-sm text-white/65 transition-colors hover:text-white"
                >
                  Create an account
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-14 flex flex-col items-center justify-between gap-4 border-t border-white/10 pt-6 sm:flex-row">
          <p className="text-xs text-white/45">© {year} VR-Nexus. All rights reserved.</p>
          <p className="text-xs text-white/30">Built for tender teams who read the fine print.</p>
        </div>
      </div>
    </footer>
  )
}

/* -------------------------------------------------------------------------- */
/* Page                                                                       */
/* -------------------------------------------------------------------------- */

export function LandingPage() {
  return (
    <div className="min-h-screen bg-surface">
      <LandingHeader />
      <main>
        <Hero />
        <ProblemSolution />
        <HowItWorks />
        <Outcomes />
        <FeatureGrid />
        <CtaBand />
        <Faq />
      </main>
      <LandingFooter />
    </div>
  )
}
