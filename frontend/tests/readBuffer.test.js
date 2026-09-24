/**
 * Read-event durability.
 *
 * These tests are about the one signal in the study that cannot be
 * reconstructed after the fact. Each case is a way a read used to be lost:
 * sent into a dead-but-OPEN socket, held only in memory across a reload, or
 * replayed under the next student's identity on a shared machine.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  bufferKey, bufferedEvents, clearAllReadBuffers, createReadSender,
} from '../src/lib/readBuffer'

const SCOPE = { userId: 'stu-1', groupSessionId: 'team-1:1' }

/** A socket stub whose readyState and delivery we control. */
function fakeSocket({ open = true, throwOnSend = false } = {}) {
  return {
    readyState: open ? 1 : 0,
    sent: [],
    send(raw) {
      if (throwOnSend) throw new Error('socket closed under us')
      this.sent.push(JSON.parse(raw))
    },
  }
}

beforeEach(() => {
  localStorage.clear()
})

describe('emit', () => {
  it('buffers before sending, so a send that never lands is not lost', () => {
    const ws = fakeSocket()
    const sender = createReadSender({ scope: SCOPE, socket: () => ws })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })

    expect(ws.sent).toHaveLength(1)
    // Still held: sending is not the same as arriving.
    expect(sender.pending()).toHaveLength(1)
    expect(sender.pending()[0].section_key).toBe('s1')
  })

  it('keeps the event when the socket throws mid-send', () => {
    const ws = fakeSocket({ throwOnSend: true })
    const sender = createReadSender({ scope: SCOPE, socket: () => ws })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })

    expect(sender.pending()).toHaveLength(1)
  })

  it('keeps the event when the socket is not open', () => {
    const ws = fakeSocket({ open: false })
    const sender = createReadSender({ scope: SCOPE, socket: () => ws })

    sender.emit({ type: 'artifact_open' })

    expect(ws.sent).toHaveLength(0)
    expect(sender.pending()).toHaveLength(1)
  })

  it('stamps an id and a client timestamp on every event', () => {
    const ws = fakeSocket()
    const sender = createReadSender({
      scope: SCOPE, socket: () => ws,
      now: () => '2026-09-22T10:00:00.000Z',
      newId: (() => { let n = 0; return () => `id-${++n}` })(),
    })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })
    sender.emit({ type: 'artifact_expand', section_key: 's2' })

    expect(ws.sent.map(e => e.event_id)).toEqual(['id-1', 'id-2'])
    expect(ws.sent[0].client_ts).toBe('2026-09-22T10:00:00.000Z')
  })
})

describe('ack', () => {
  it('only an ack removes an event from the buffer', () => {
    const ws = fakeSocket()
    const sender = createReadSender({
      scope: SCOPE, socket: () => ws, newId: () => 'evt-1',
    })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })
    expect(sender.pending()).toHaveLength(1)

    sender.ack('evt-1')
    expect(sender.pending()).toHaveLength(0)
  })

  it('an ack for something else leaves the buffer alone', () => {
    const ws = fakeSocket()
    const sender = createReadSender({
      scope: SCOPE, socket: () => ws, newId: () => 'evt-1',
    })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })
    sender.ack('a-different-id')

    expect(sender.pending()).toHaveLength(1)
  })
})

describe('flush', () => {
  it('replays everything unacked, preserving the original client_ts', () => {
    const down = fakeSocket({ open: false })
    let current = down
    let n = 0
    const sender = createReadSender({
      scope: SCOPE,
      socket: () => current,
      now: () => `2026-09-22T10:00:0${n}.000Z`,
      newId: () => `id-${++n}`,
    })

    // Two reads while the socket is down.
    sender.emit({ type: 'artifact_expand', section_key: 's1' })
    sender.emit({ type: 'artifact_dwell', section_key: 's1', duration_ms: 9000 })
    expect(down.sent).toHaveLength(0)

    // Reconnect.
    const up = fakeSocket()
    current = up
    sender.flush()

    expect(up.sent.map(e => e.section_key)).toEqual(['s1', 's1'])
    // The timestamps are when the reads HAPPENED, not when they arrived.
    expect(up.sent[0].client_ts).toBe('2026-09-22T10:00:01.000Z')
    expect(up.sent[1].client_ts).toBe('2026-09-22T10:00:02.000Z')
    // Still unacked, so still held.
    expect(sender.pending()).toHaveLength(2)
  })

  it('stops at the first failure and keeps the rest buffered', () => {
    const ws = fakeSocket()
    const sender = createReadSender({ scope: SCOPE, socket: () => ws })
    sender.emit({ type: 'artifact_expand', section_key: 's1' })
    sender.emit({ type: 'artifact_expand', section_key: 's2' })

    ws.sent.length = 0
    ws.readyState = 0            // dropped again before the flush
    sender.flush()

    expect(ws.sent).toHaveLength(0)
    expect(sender.pending()).toHaveLength(2)
  })

  it('survives a page reload: the buffer is storage, not memory', () => {
    const down = fakeSocket({ open: false })
    const before = createReadSender({
      scope: SCOPE, socket: () => down, newId: () => 'evt-reload',
    })
    before.emit({ type: 'artifact_expand', section_key: 's1' })

    // A reload constructs a brand new sender over the same storage — the case
    // an in-memory queue loses, and the one a student triggers by refreshing
    // when the page looks stuck.
    const up = fakeSocket()
    const after = createReadSender({ scope: SCOPE, socket: () => up })
    expect(after.pending()).toHaveLength(1)

    after.flush()
    expect(up.sent[0].event_id).toBe('evt-reload')
  })
})

describe('scoping', () => {
  it('one student cannot flush another student\'s buffered reads', () => {
    const down = fakeSocket({ open: false })
    const a = createReadSender({
      scope: { userId: 'stu-A', groupSessionId: 'team-1:1' }, socket: () => down,
    })
    a.emit({ type: 'artifact_expand', section_key: 's1' })

    // Student B logs in on the same browser. The server attributes an event to
    // whoever is authenticated, so replaying A's read here would fabricate a
    // read by B in a permanent log.
    const up = fakeSocket()
    const b = createReadSender({
      scope: { userId: 'stu-B', groupSessionId: 'team-1:1' }, socket: () => up,
    })

    expect(b.pending()).toHaveLength(0)
    b.flush()
    expect(up.sent).toHaveLength(0)
  })

  it('separates sessions for the same student', () => {
    const ws = fakeSocket({ open: false })
    const s1 = createReadSender({
      scope: { userId: 'stu-1', groupSessionId: 'team-1:1' }, socket: () => ws,
    })
    s1.emit({ type: 'artifact_expand', section_key: 's1' })

    const s2 = createReadSender({
      scope: { userId: 'stu-1', groupSessionId: 'team-1:2' }, socket: () => ws,
    })
    expect(s2.pending()).toHaveLength(0)
    expect(s1.pending()).toHaveLength(1)
  })

  it('clearAllReadBuffers wipes every scope, for logout on a shared machine', () => {
    const ws = fakeSocket({ open: false })
    createReadSender({ scope: { userId: 'a', groupSessionId: 'g:1' }, socket: () => ws })
      .emit({ type: 'artifact_open' })
    createReadSender({ scope: { userId: 'b', groupSessionId: 'g:2' }, socket: () => ws })
      .emit({ type: 'artifact_open' })

    expect(bufferedEvents(bufferKey({ userId: 'a', groupSessionId: 'g:1' }))).toHaveLength(1)

    clearAllReadBuffers()

    expect(bufferedEvents(bufferKey({ userId: 'a', groupSessionId: 'g:1' }))).toHaveLength(0)
    expect(bufferedEvents(bufferKey({ userId: 'b', groupSessionId: 'g:2' }))).toHaveLength(0)
  })
})

describe('storage failure', () => {
  it('still sends when localStorage refuses to write', () => {
    const ws = fakeSocket()
    const sender = createReadSender({ scope: SCOPE, socket: () => ws })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })

    sender.emit({ type: 'artifact_expand', section_key: 's1' })

    // Durability across a reload is lost, but the event itself is not: it went
    // out on the wire. Dropping it instead would be the worse failure.
    expect(ws.sent).toHaveLength(1)
  })
})
