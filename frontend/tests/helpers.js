import { vi } from 'vitest'

/**
 * Drive document visibility.
 *
 * HONEST LIMIT: jsdom never fires `visibilitychange` on its own and keeps
 * `document.visibilityState` read-only at 'visible'. There is no API to flip it,
 * so we redefine the property and dispatch the event by hand.
 *
 * What this proves: our listener/timer/cleanup logic reacts correctly to the
 * signal. What it does NOT prove: that a real browser emits `visibilitychange`
 * on an OS tab switch, window minimise, or mobile backgrounding. That half of
 * the contract is browser behaviour we are taking on faith (it is well
 * specified and stable, but it is faith, not coverage).
 */
export function setVisibility(state) {
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  })
  Object.defineProperty(document, 'hidden', {
    configurable: true,
    get: () => state === 'hidden',
  })
  document.dispatchEvent(new Event('visibilitychange'))
}

export function resetVisibility() {
  setVisibility('visible')
}

/**
 * A WebSocket stand-in we can drive from the test.
 *
 * jsdom ships a real WebSocket that would attempt a real network connection, so
 * every test that mounts a socket-owning component installs this instead. It is
 * also the only way to push server frames (artifact_state, read_event_ack) into
 * the component under test.
 */
export class FakeWebSocket {
  static instances = []
  static OPEN = 1
  static CLOSED = 3

  constructor(url) {
    this.url = url
    this.readyState = FakeWebSocket.OPEN
    this.sent = []
    this.closed = false
    this.onopen = null
    this.onclose = null
    this.onerror = null
    this.onmessage = null
    FakeWebSocket.instances.push(this)
  }

  send(raw) {
    this.sent.push(JSON.parse(raw))
  }

  close() {
    this.closed = true
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.({})
  }

  /** Push a server frame at the component. */
  receive(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  /** Frames of one type that the component sent to the server. */
  sentOfType(type) {
    return this.sent.filter((m) => m.type === type)
  }

  static get last() {
    return FakeWebSocket.instances[FakeWebSocket.instances.length - 1]
  }

  static reset() {
    FakeWebSocket.instances = []
  }
}

export function installFakeWebSocket() {
  FakeWebSocket.reset()
  vi.stubGlobal('WebSocket', FakeWebSocket)
  return FakeWebSocket
}

/** Collects the events a tracker hands to `send`. */
export function recorder() {
  const events = []
  const send = (e) => { events.push(e) }
  return { events, send, typesOf: (t) => events.filter((e) => e.type === t) }
}
