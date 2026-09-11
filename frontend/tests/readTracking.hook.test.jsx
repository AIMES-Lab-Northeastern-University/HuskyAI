import { StrictMode, useEffect, useRef } from 'react'
import { render, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useSectionReadTracking, clearAllReadBuffers } from '../src/lib/readTracking'
import { setVisibility, resetVisibility, recorder } from './helpers'

/**
 * The dwell timer as the app actually runs it: through the React hook, inside
 * <StrictMode>, which is how main.jsx mounts the tree.
 *
 * StrictMode matters and is not ceremony here. React 18 simulates a remount on
 * first mount (effect -> cleanup -> effect). Anything that registers a listener
 * outside the effect but tears it down inside the cleanup ends up with the
 * listener gone while the object still looks alive. Rendering without
 * StrictMode hides exactly that class of bug, so these tests opt in.
 */

const SCOPE = { userId: 'u-1', groupSessionId: 'g-1:1' }

function Harness({ send, dwellMs, onTracker }) {
  const tracker = useSectionReadTracking({
    send,
    surface: 'test_surface',
    scope: SCOPE,
    dwellMs,
    React: { useEffect, useRef },
  })
  onTracker?.(tracker)
  return (
    <div>
      <button onClick={() => tracker.open('s1', 'section_expand')}>open</button>
      <button onClick={() => tracker.close('s1')}>close</button>
    </div>
  )
}

function mount({ dwellMs = 3000 } = {}) {
  const rec = recorder()
  let tracker = null
  const utils = render(
    <StrictMode>
      <Harness send={rec.send} dwellMs={dwellMs} onTracker={(t) => { tracker = t }} />
    </StrictMode>,
  )
  return { ...utils, ...rec, getTracker: () => tracker }
}

const openSection = (utils) => fireEvent.click(utils.getByText('open'))
const closeSection = (utils) => fireEvent.click(utils.getByText('close'))
const advance = (ms) => act(() => { vi.advanceTimersByTime(ms) })

describe('useSectionReadTracking dwell timer (StrictMode)', () => {
  beforeEach(() => {
    // Date must be faked alongside setTimeout: the dwell maths mixes
    // Date.now() deltas with setTimeout, so faking only one of them would
    // silently measure the wrong thing.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    resetVisibility()
    localStorage.clear()
    // Open episodes deliberately outlive an unmount now (that is the whole
    // point of the dwell unification), so they also outlive a test. Reset via
    // the real logout path rather than a test-only back door.
    clearAllReadBuffers()
  })

  afterEach(() => {
    vi.useRealTimers()
    resetVisibility()
  })

  it('does not fire before the dwell threshold', () => {
    const t = mount()
    openSection(t)
    advance(2999)
    expect(t.events).toHaveLength(0)
  })

  it('fires once the threshold is met', () => {
    const t = mount()
    openSection(t)
    advance(3000)
    expect(t.typesOf('section_read')).toHaveLength(1)
    expect(t.events[0]).toMatchObject({
      section_key: 's1',
      event_type: 'section_expand',
      surface: 'test_surface',
    })
  })

  it('fires nothing for a fast open/close under the threshold', () => {
    const t = mount()
    openSection(t)
    advance(500)
    closeSection(t)
    advance(10000)
    expect(t.events).toHaveLength(0)
  })

  /**
   * The one most likely to look correct and silently not work.
   *
   * A hidden stretch must not count toward the threshold. Opening a section and
   * immediately backgrounding the tab for a minute is not reading it, so the
   * event must still be waiting when the student comes back -- and must then
   * need the full remaining time, not fire instantly.
   */
  it('does not count hidden time toward the dwell threshold', () => {
    const t = mount()
    openSection(t)

    advance(2000)            // 2s of genuine, visible reading
    setVisibility('hidden')
    advance(60000)           // a minute in the background

    expect(t.events).toHaveLength(0)

    setVisibility('visible')
    advance(999)             // 2.999s of visible time in total
    expect(t.events).toHaveLength(0)

    advance(1)               // crosses 3s of *visible* time
    expect(t.typesOf('section_read')).toHaveLength(1)
    // Recorded dwell is visible time only, not wall-clock since open.
    expect(t.events[0].dwell_ms).toBeGreaterThanOrEqual(3000)
    expect(t.events[0].dwell_ms).toBeLessThan(4000)
  })

  it('fires exactly once per open, not repeatedly', () => {
    const t = mount()
    openSection(t)
    advance(30000)
    expect(t.events).toHaveLength(1)
  })

  it('survives rapid open/close/open without double-firing or dropping', () => {
    const t = mount()
    for (let i = 0; i < 5; i++) {
      openSection(t)
      advance(200)
      closeSection(t)
      advance(50)
    }
    expect(t.events).toHaveLength(0)   // never past threshold

    openSection(t)                      // now a real read
    advance(3000)
    expect(t.events).toHaveLength(1)
  })

  it('restarts dwell from zero after an explicit close', () => {
    const t = mount()
    openSection(t)
    advance(2900)
    closeSection(t)      // discards the episode by design
    openSection(t)
    advance(2900)        // 5.8s total, but never 3s in one episode
    expect(t.events).toHaveLength(0)
    advance(100)
    expect(t.events).toHaveLength(1)
  })
})
