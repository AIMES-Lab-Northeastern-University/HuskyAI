import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  createReadTracker,
  bufferKey,
  bufferEvent,
  bufferedEvents,
  ackEvent,
  clearAllReadBuffers,
  READ_DWELL_MS,
} from '../src/lib/readTracking'
import { setVisibility, resetVisibility, recorder } from './helpers'

const A = { userId: 'student-a', groupSessionId: 'g-1:1' }
const B = { userId: 'student-b', groupSessionId: 'g-1:1' }

function tracker(scope, send, dwellMs = READ_DWELL_MS) {
  const t = createReadTracker({ send, surface: 'artifact_panel', scope, dwellMs })
  t.attach()
  return t
}

describe('read-event buffer', () => {
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

  it('scopes the key to the student and the group session', () => {
    expect(bufferKey(A)).not.toEqual(bufferKey(B))
    expect(bufferKey(A)).not.toEqual(bufferKey({ ...A, groupSessionId: 'g-1:2' }))
    expect(bufferKey()).toContain('anon')
  })

  it('never buffers the same event twice', () => {
    const key = bufferKey(A)
    const event = { event_id: 'e-1', section_key: 's1' }
    bufferEvent(key, event)
    bufferEvent(key, event)
    expect(bufferedEvents(key)).toHaveLength(1)
  })

  it('removes an event only when acked by id', () => {
    const key = bufferKey(A)
    bufferEvent(key, { event_id: 'e-1' })
    bufferEvent(key, { event_id: 'e-2' })

    ackEvent(key, 'e-nope')
    expect(bufferedEvents(key)).toHaveLength(2)

    ackEvent(key, 'e-1')
    expect(bufferedEvents(key).map((e) => e.event_id)).toEqual(['e-2'])
  })

  /**
   * The leak the scoping was introduced to close, pinned as a regression.
   *
   * The buffer key used to be one global 'husky_read_events'. Student A leaves
   * an unacked read behind, logs out, student B logs in on the same browser, and
   * B's socket flushes A's event. The server keys idempotency on the
   * authenticated sender, so it would land as B having read that section: a
   * fabricated event in a permanent research log, attributed to the wrong
   * student. This fails if the key ever stops being scoped.
   */
  it("never replays one student's unacked reads under another's identity", () => {
    const aSend = recorder()
    const a = tracker(A, aSend.send)
    a.open('problem', 'section_expand')
    vi.advanceTimersByTime(READ_DWELL_MS)

    expect(aSend.typesOf('section_read')).toHaveLength(1)
    expect(bufferedEvents(bufferKey(A))).toHaveLength(1)   // unacked, still durable
    a.detach()

    // Student B now uses the same browser.
    const bSend = recorder()
    const b = tracker(B, bSend.send)
    expect(bufferedEvents(b.bufferKey)).toHaveLength(0)

    b.flush()
    expect(bSend.events).toHaveLength(0)
  })

  it('drops every buffer on logout, across students and sessions', () => {
    bufferEvent(bufferKey(A), { event_id: 'a-1' })
    bufferEvent(bufferKey(B), { event_id: 'b-1' })
    bufferEvent(bufferKey({ ...A, groupSessionId: 'g-9:4' }), { event_id: 'a-2' })
    localStorage.setItem('unrelated_key', 'keep me')

    clearAllReadBuffers()

    expect(bufferedEvents(bufferKey(A))).toHaveLength(0)
    expect(bufferedEvents(bufferKey(B))).toHaveLength(0)
    expect(bufferedEvents(bufferKey({ ...A, groupSessionId: 'g-9:4' }))).toHaveLength(0)
    expect(localStorage.getItem('unrelated_key')).toBe('keep me')
  })

  it('also drops in-flight dwell state on logout', () => {
    const rec = recorder()
    const a = tracker(A, rec.send)
    a.open('problem')
    vi.advanceTimersByTime(2000)

    clearAllReadBuffers()

    // A part-read section must not carry into the next student's session.
    const next = tracker(A, rec.send)
    expect(next.expandedKeys()).toEqual([])
    vi.advanceTimersByTime(60000)
    expect(rec.events).toHaveLength(0)
  })

  it('cancels pending dwell timers on logout rather than leaving them queued', () => {
    const rec = recorder()
    const a = tracker(A, rec.send)
    a.open('problem')
    expect(vi.getTimerCount()).toBeGreaterThan(0)

    clearAllReadBuffers()

    // Emptying the episode maps alone would make the queued callback a no-op,
    // which is why no event fires either way. This pins the timer itself being
    // cancelled, so logout does not leave work pending on a dead identity.
    expect(vi.getTimerCount()).toBe(0)
  })

  it('replays unacked events on flush and stops once acked', () => {
    const rec = recorder()
    const t = tracker(A, rec.send)
    t.open('problem')
    vi.advanceTimersByTime(READ_DWELL_MS)

    const [event] = rec.events
    rec.events.length = 0

    t.flush()
    expect(rec.events.map((e) => e.event_id)).toEqual([event.event_id])

    t.ack(event.event_id)
    rec.events.length = 0
    t.flush()
    expect(rec.events).toHaveLength(0)
  })

  it('keeps the event when localStorage is unavailable', () => {
    const rec = recorder()
    const t = tracker(A, rec.send)
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })

    t.open('problem')
    vi.advanceTimersByTime(READ_DWELL_MS)

    // Durability across a reload is lost, but the event still reaches the socket.
    expect(rec.typesOf('section_read')).toHaveLength(1)
    spy.mockRestore()
  })

  it('registers no visibility listener until attach is called', () => {
    const spy = vi.spyOn(document, 'addEventListener')
    createReadTracker({ send: () => {}, surface: 's', scope: A })

    // Construction happens during render. A listener registered there, but torn
    // down by an effect cleanup, is what StrictMode turned into a silently dead
    // visibility pause.
    expect(spy.mock.calls.filter(([type]) => type === 'visibilitychange')).toHaveLength(0)
    spy.mockRestore()
  })

  it('does not start a timer without an explicit open', () => {
    const rec = recorder()
    tracker(A, rec.send)
    setVisibility('hidden')
    setVisibility('visible')
    vi.advanceTimersByTime(120000)
    expect(rec.events).toHaveLength(0)
  })
})
