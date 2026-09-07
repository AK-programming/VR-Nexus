/**
 * Domain-model unit tests for Tender Analysis.
 *
 * These functions decide what the tender screens draw — which pipeline node is
 * lit, whether a row still spins, how a polled status becomes a progress frame —
 * so they are exactly the logic worth pinning down without a browser. Pure in,
 * pure out; no DOM, no network.
 */
import { describe, expect, it } from 'vitest'
import {
  hasReviewableAnalysis,
  isInFlight,
  isSettled,
  isSocketTerminal,
  progressFromDetail,
  requirementPriority,
  stageStates,
  tenderTitle,
} from '@/models/tenders'

describe('requirementPriority', () => {
  it('maps the mandatory tri-state', () => {
    expect(requirementPriority(true)).toBe('mandatory')
    expect(requirementPriority(false)).toBe('optional')
    expect(requirementPriority(null)).toBe('unspecified')
  })
})

describe('status predicates', () => {
  it('isInFlight is true only for the working stages', () => {
    expect(isInFlight('parsing')).toBe(true)
    expect(isInFlight('matching')).toBe(true)
    expect(isInFlight('ready_for_review')).toBe(false)
    expect(isInFlight('finalized')).toBe(false)
  })

  it('isSettled covers review, finalized and failed', () => {
    expect(isSettled('ready_for_review')).toBe(true)
    expect(isSettled('finalized')).toBe(true)
    expect(isSettled('failed')).toBe(true)
    expect(isSettled('parsing')).toBe(false)
  })

  it('isSocketTerminal is only the two terminal outcomes', () => {
    expect(isSocketTerminal('finalized')).toBe(true)
    expect(isSocketTerminal('failed')).toBe(true)
    expect(isSocketTerminal('ready_for_review')).toBe(false)
  })
})

describe('stageStates', () => {
  it('marks stages before the current done, the current active, the rest pending', () => {
    const states = stageStates('extracting')
    expect(states.uploaded).toBe('done')
    expect(states.chunking).toBe('done')
    expect(states.extracting).toBe('active')
    expect(states.matching).toBe('pending')
    expect(states.ready_for_review).toBe('pending')
  })

  it('treats finalized as a fully complete rail', () => {
    const states = stageStates('finalized')
    expect(states.uploaded).toBe('done')
    expect(states.ready_for_review).toBe('done')
  })

  it('fails the rail from the break point when failedAt is known', () => {
    const states = stageStates('failed', 'matching')
    expect(states.merging).toBe('done')
    expect(states.matching).toBe('failed')
    expect(states.reporting).toBe('failed')
  })

  it('fails from the first working step when failedAt is unknown', () => {
    const states = stageStates('failed')
    expect(states.uploaded).toBe('done')
    expect(states.parsing).toBe('failed')
  })
})

describe('progressFromDetail', () => {
  it('derives the step index and label from the status position', () => {
    const progress = progressFromDetail({
      status: 'matching',
      progress_percent: 62,
      progress_message: 'Matching evidence...',
      extracted_requirements_count: 42,
      updated_at: null,
    })
    expect(progress.currentStep).toBe(6)
    expect(progress.totalSteps).toBe(9)
    expect(progress.stepLabel).toBe('Matching evidence')
    expect(progress.percent).toBe(62)
    expect(progress.extractedRequirementsCount).toBe(42)
  })
})

describe('hasReviewableAnalysis', () => {
  it('is true once requirements exist or the tender has settled', () => {
    expect(hasReviewableAnalysis({ status: 'parsing', extracted_requirements_count: 0 })).toBe(false)
    expect(hasReviewableAnalysis({ status: 'parsing', extracted_requirements_count: 5 })).toBe(true)
    expect(
      hasReviewableAnalysis({ status: 'ready_for_review', extracted_requirements_count: 0 }),
    ).toBe(true)
  })
})

describe('tenderTitle', () => {
  it('prefers the name and falls back to the filename', () => {
    expect(tenderTitle({ name: 'WASA Water Supply', original_filename: 'wasa.pdf' })).toBe(
      'WASA Water Supply',
    )
    expect(tenderTitle({ name: '  ', original_filename: 'wasa.pdf' })).toBe('wasa.pdf')
    expect(tenderTitle({ name: null, original_filename: 'wasa.pdf' })).toBe('wasa.pdf')
  })
})
