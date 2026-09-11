import { StrictMode } from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import ArtifactPanel from '../src/components/ArtifactPanel'
import { bufferedEvents, clearAllReadBuffers } from '../src/lib/readTracking'
import { setVisibility, resetVisibility, recorder } from './helpers'

/**
 * ArtifactPanel through a real component tree: real clicks, real effects, real
 * mount/unmount. The static coverage guard in
 * backend/tests/test_read_event_coverage.py proves the hook is CALLED here;
 * these prove the call actually produces events at runtime.
 */

const SECTIONS = [
  { key: 'problem', title: 'Problem statement', content: 'ALPHA-BODY-TEXT', version: 1 },
  { key: 'approach', title: 'Approach', content: 'BETA-BODY-TEXT', version: 2 },
]

function mountPanel({ send, onTracker, sections = SECTIONS } = {}) {
  return render(
    <StrictMode>
      <ArtifactPanel
        sections={sections}
        locks={[]}
        meId="u-1"
        groupSessionId="g-1:1"
        send={send}
        onRequestLock={() => {}}
        onReleaseLock={() => {}}
        onWrite={() => {}}
        onTracker={onTracker}
      />
    </StrictMode>,
  )
}

const advance = (ms) => act(() => { vi.advanceTimersByTime(ms) })
const showToggleFor = (title) =>
  screen.getByText(title).closest('button')

/**
 * Distinct read episodes, not raw send calls.
 *
 * flush() deliberately replays every still-unacked event whenever the socket
 * comes back or the pane remounts, and StrictMode runs that effect twice, so one
 * read can legitimately reach `send` several times. The server dedupes on the
 * idempotency key, so what must not grow is the number of distinct event ids.
 */
const distinctReads = (rec) =>
  [...new Set(rec.events.filter((e) => e.type === 'section_read').map((e) => e.event_id))]

describe('ArtifactPanel read logging, mounted', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    resetVisibility()
    localStorage.clear()
    clearAllReadBuffers()
  })

  afterEach(() => {
    vi.useRealTimers()
    resetVisibility()
  })

  it('renders section titles without mounting any section content', () => {
    const { send } = recorder()
    mountPanel({ send })

    expect(screen.getByText('Problem statement')).toBeInTheDocument()
    expect(screen.getByText('Approach')).toBeInTheDocument()

    // Not "hidden" -- absent. The requirement is that content is never on
    // screen without an explicit open, so the assertion is that it was never
    // rendered at all, which a CSS-visibility check would not establish.
    expect(screen.queryByText('ALPHA-BODY-TEXT')).toBeNull()
    expect(screen.queryByText('BETA-BODY-TEXT')).toBeNull()
  })

  it('emits no read event on mount, render or the passage of time alone', () => {
    const rec = recorder()
    mountPanel({ send: rec.send })
    advance(60000)
    expect(rec.events).toHaveLength(0)
  })

  it('clicking Show mounts the content and produces a read event past dwell', () => {
    const rec = recorder()
    mountPanel({ send: rec.send })

    fireEvent.click(showToggleFor('Problem statement'))
    expect(screen.getByText('ALPHA-BODY-TEXT')).toBeInTheDocument()

    advance(2999)
    expect(rec.events).toHaveLength(0)

    advance(1)
    expect(rec.typesOf('section_read')).toHaveLength(1)
    expect(rec.events[0]).toMatchObject({
      section_key: 'problem',
      event_type: 'section_expand',
      surface: 'artifact_panel',
    })
  })

  it('opening one section does not log a read of another', () => {
    const rec = recorder()
    mountPanel({ send: rec.send })

    fireEvent.click(showToggleFor('Problem statement'))
    advance(5000)

    expect(rec.events.map((e) => e.section_key)).toEqual(['problem'])
    expect(screen.queryByText('BETA-BODY-TEXT')).toBeNull()
  })

  it('a click-through under the dwell floor unmounts content and logs nothing', () => {
    const rec = recorder()
    mountPanel({ send: rec.send })

    const toggle = showToggleFor('Problem statement')
    fireEvent.click(toggle)
    advance(400)
    fireEvent.click(toggle)          // collapsed again

    expect(screen.queryByText('ALPHA-BODY-TEXT')).toBeNull()
    advance(60000)
    expect(rec.events).toHaveLength(0)
  })

  /**
   * Bug: GroupChat's read_event_ack / read_event_rejected handlers called
   * readTrackerRef.current?.ack(...) but nothing ever assigned that ref, so
   * both were silent no-ops. The buffer was therefore never pruned and every
   * reconnect replayed the student's entire read history for the session.
   */
  it('hands its tracker up so acks can prune the durable buffer', () => {
    const rec = recorder()
    let tracker = null
    mountPanel({ send: rec.send, onTracker: (t) => { tracker = t } })

    expect(tracker).not.toBeNull()

    fireEvent.click(showToggleFor('Problem statement'))
    advance(3000)

    const [event] = rec.events
    expect(bufferedEvents(tracker.bufferKey)).toHaveLength(1)

    tracker.ack(event.event_id)
    expect(bufferedEvents(tracker.bufferKey)).toHaveLength(0)
  })

  it('buffers the event before sending, so a dead socket cannot lose it', () => {
    let tracker = null
    const throwingSend = () => { throw new Error('socket down') }
    mountPanel({ send: throwingSend, onTracker: (t) => { tracker = t } })

    fireEvent.click(showToggleFor('Problem statement'))
    advance(3000)

    expect(bufferedEvents(tracker.bufferKey)).toHaveLength(1)
  })

  /**
   * The unification (decision 3). Switching the centre column to another tab
   * unmounts this pane; that must behave like hiding the browser tab, not like
   * collapsing the section. Otherwise 5.8s of genuine reading scores as a read
   * or a non-read purely according to how the student navigated away.
   */
  describe('dwell survives the pane being unmounted (in-app tab switch)', () => {
    it('resumes with banked time and the section still open', () => {
      const rec = recorder()
      const first = mountPanel({ send: rec.send })

      fireEvent.click(showToggleFor('Problem statement'))
      advance(2000)                    // 2s of real reading
      act(() => { first.unmount() })   // switched to "My coach"

      advance(60000)                   // time away must not count
      expect(rec.events).toHaveLength(0)

      mountPanel({ send: rec.send })   // switched back to "Artifact"

      // Still open, because the episode was paused rather than ended.
      expect(screen.getByText('ALPHA-BODY-TEXT')).toBeInTheDocument()

      advance(999)
      expect(rec.events).toHaveLength(0)
      advance(1)                       // 3s of visible time, across two mounts
      expect(rec.typesOf('section_read')).toHaveLength(1)
    })

    it('scores the same as an OS tab switch for identical reading time', () => {
      // Two students, 2.9s + 2.9s of real reading each. One switches app tabs
      // between the stretches, the other backgrounds the browser. Same outcome.
      const viaAppTab = recorder()
      const first = mountPanel({ send: viaAppTab.send })
      fireEvent.click(showToggleFor('Problem statement'))
      advance(2900)
      act(() => { first.unmount() })
      advance(5000)
      const second = mountPanel({ send: viaAppTab.send })
      advance(2900)
      act(() => { second.unmount() })

      clearAllReadBuffers()

      const viaOsTab = recorder()
      mountPanel({ send: viaOsTab.send })
      fireEvent.click(showToggleFor('Problem statement'))
      advance(2900)
      setVisibility('hidden')
      advance(5000)
      setVisibility('visible')
      advance(2900)

      expect(distinctReads(viaAppTab)).toHaveLength(1)
      expect(distinctReads(viaOsTab)).toHaveLength(1)
    })

    it('still discards the episode when the student explicitly collapses', () => {
      const rec = recorder()
      const panel = mountPanel({ send: rec.send })

      const toggle = showToggleFor('Problem statement')
      fireEvent.click(toggle)
      advance(2900)
      fireEvent.click(toggle)          // explicit collapse ends the episode
      act(() => { panel.unmount() })

      mountPanel({ send: rec.send })
      expect(screen.queryByText('ALPHA-BODY-TEXT')).toBeNull()

      fireEvent.click(showToggleFor('Problem statement'))
      advance(2900)                    // 5.8s total, never 3s in one episode
      expect(rec.events).toHaveLength(0)
    })

    it('does not re-fire a read that already completed', () => {
      const rec = recorder()
      const panel = mountPanel({ send: rec.send })

      fireEvent.click(showToggleFor('Problem statement'))
      advance(3000)
      expect(distinctReads(rec)).toHaveLength(1)

      act(() => { panel.unmount() })
      mountPanel({ send: rec.send })
      advance(60000)

      // Remounting replays the unacked event (by design), but it is the same
      // episode: one read, not two.
      expect(distinctReads(rec)).toHaveLength(1)
    })

    it('stops replaying an event once the server has acked it', () => {
      const rec = recorder()
      let tracker = null
      const panel = mountPanel({ send: rec.send, onTracker: (t) => { tracker = t } })

      fireEvent.click(showToggleFor('Problem statement'))
      advance(3000)
      tracker.ack(rec.events[0].event_id)   // the wiring bug #1 restored
      const sendsBefore = rec.events.length

      act(() => { panel.unmount() })
      mountPanel({ send: rec.send })
      advance(1000)

      expect(rec.events).toHaveLength(sendsBefore)
    })
  })
})
