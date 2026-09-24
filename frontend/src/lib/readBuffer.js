/**
 * Durable delivery for read events.
 *
 * Read events are the one thing in this study that cannot be reconstructed
 * after the fact: a write leaves a revision, an evaluation leaves a score, but
 * a read that was never delivered is gone. So delivery is at-least-once and the
 * client keeps a copy until the server acks it by `event_id`. The server dedupes
 * on that same id (`study_events.idempotency_key` is unique), which is why
 * re-sending is always safe and dropping never is.
 *
 * The buffer lives in localStorage rather than memory. In memory it survives a
 * dropped socket but not the thing a student actually does when the page looks
 * stuck, which is reload it — and that is exactly the moment the buffer is
 * holding unsent reads.
 *
 * This module deliberately does NOT define what counts as a read, or when an
 * event fires. Those are the event vocabulary in docs/event-schema.md
 * (`open`, `section_expand`, `dwell`, `close`) and the emit points in
 * CoachWorkspace. This is only the part that makes sure what fired arrives.
 */

const BUFFER_PREFIX = 'husky_read_events'

/**
 * The buffer key is scoped to the student AND the group session.
 *
 * A single global key is a data-integrity hole on a shared machine: student A
 * buffers an unacked read, logs out, student B logs in in the same browser, and
 * B's socket flushes A's event. The server attributes an event to the
 * authenticated sender, so it would land as B having read that section — a
 * fabricated row in a permanent research log, attributed to the wrong student.
 * Scoping means B's buffer never contains A's events.
 */
export function bufferKey({ userId, groupSessionId } = {}) {
  return `${BUFFER_PREFIX}:${userId || 'anon'}:${groupSessionId || 'none'}`
}

function loadBuffer(key) {
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveBuffer(key, events) {
  try {
    localStorage.setItem(key, JSON.stringify(events))
  } catch {
    /* Storage full or blocked. The caller's in-memory copy still carries the
       event for this session; only cross-reload durability is lost. Never drop
       the event itself. */
  }
}

export function bufferedEvents(key) {
  return loadBuffer(key)
}

/** Record an event as sent-but-unacked. Idempotent on `event_id`. */
export function bufferEvent(key, event) {
  const events = loadBuffer(key)
  if (events.some(e => e.event_id === event.event_id)) return events
  events.push(event)
  saveBuffer(key, events)
  return events
}

/** The server confirmed this id; stop replaying it. */
export function ackEvent(key, eventId) {
  const remaining = loadBuffer(key).filter(e => e.event_id !== eventId)
  saveBuffer(key, remaining)
  return remaining
}

export function clearBuffer(key) {
  saveBuffer(key, [])
}

/**
 * Drop every read-event buffer in this browser. Call on logout, so nothing one
 * student left behind can be replayed under the next student's identity.
 */
export function clearAllReadBuffers() {
  try {
    const doomed = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(BUFFER_PREFIX)) doomed.push(k)
    }
    doomed.forEach(k => localStorage.removeItem(k))
  } catch {
    /* storage unavailable; nothing buffered to leak either */
  }
}

/**
 * Wrap a socket send so every read event is durable.
 *
 * `emit` buffers first and sends second — the reverse would lose any event whose
 * send is accepted by a socket that is OPEN but already dead, which is the
 * normal shape of a dropped wifi connection: readyState lags reality by
 * seconds. `flush` replays everything still unacked and, unlike a queue that
 * clears on send, keeps entries until the ack arrives.
 */
export function createReadSender({ scope, socket, now = () => new Date().toISOString(), newId }) {
  const key = bufferKey(scope)
  const makeId = newId || (() => {
    try {
      if (crypto?.randomUUID) return crypto.randomUUID()
    } catch { /* fall through */ }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`
  })

  function rawSend(msg) {
    const ws = socket()
    if (!ws || ws.readyState !== 1 /* OPEN */) return false
    try {
      ws.send(JSON.stringify(msg))
      return true
    } catch {
      return false
    }
  }

  return {
    bufferKey: key,

    /** Fire one read event. Buffered before it is sent, always. */
    emit(payload) {
      const event = { ...payload, event_id: makeId(), client_ts: now() }
      bufferEvent(key, event)
      rawSend(event)
      return event
    },

    /** Replay everything the server has not acked yet. Called on (re)connect. */
    flush() {
      const pending = loadBuffer(key)
      for (const event of pending) {
        if (!rawSend(event)) break   // socket down again; keep the rest buffered
      }
      return pending.length
    },

    /** Server confirmed an id. */
    ack(eventId) {
      return ackEvent(key, eventId)
    },

    pending() {
      return loadBuffer(key)
    },
  }
}
