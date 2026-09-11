/**
 * Read tracking for shared-artifact sections.
 *
 * What counts as a read (the agreed definition):
 *   - the student EXPLICITLY opens or expands a section, and
 *   - stays on it for at least READ_DWELL_MS of *visible* time.
 *
 * Rendered is not read. Nothing here is wired to mount, layout or effect-on-load:
 * the only way a timer starts is an explicit call from an open/expand handler.
 * A section scrolling into view, the artifact loading, or a background prefetch
 * can never produce an event.
 *
 * Tab switching pauses the timer. A student who opens a section and immediately
 * switches tabs is not reading it, so only foreground time accumulates.
 *
 * Events are buffered in localStorage and replayed on reconnect. An entry is
 * removed only when the server acks it by event_id, so a drop mid-dwell or
 * mid-send costs nothing. Duplicates are fine -- the server dedupes on the
 * idempotency key rather than dropping. Nothing is ever sampled.
 */

export const READ_DWELL_MS = 3000

const BUFFER_PREFIX = 'husky_read_events'

/**
 * The buffer key is scoped to the student AND the group session.
 *
 * It used to be a single global key, which is a data-integrity hole on a shared
 * machine: student A buffers an unacked read, logs out, student B logs in on the
 * same browser, and B's socket flushes A's event. The server keys idempotency on
 * the *authenticated sender*, so it would land as B having read that section --
 * a fabricated event in a permanent research log, attributed to the wrong
 * student. Scoping means B's tracker never sees A's buffer.
 */
export function bufferKey({ userId, groupSessionId } = {}) {
  return `${BUFFER_PREFIX}:${userId || 'anon'}:${groupSessionId || 'none'}`
}

/* ─── localStorage buffer ─── */

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
    /* Storage full or blocked. The in-memory queue still carries the event for
       this session; we just lose cross-reload durability. Never drop silently
       in a way that loses the event within the session. */
  }
}

export function bufferedEvents(key) {
  return loadBuffer(key)
}

export function bufferEvent(key, event) {
  const events = loadBuffer(key)
  if (events.some(e => e.event_id === event.event_id)) return events
  events.push(event)
  saveBuffer(key, events)
  return events
}

export function ackEvent(key, eventId) {
  const remaining = loadBuffer(key).filter(e => e.event_id !== eventId)
  saveBuffer(key, remaining)
  return remaining
}

export function clearBuffer(key) {
  saveBuffer(key, [])
}

/**
 * Drop every read-event buffer on this browser. Call on logout so nothing a
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
  // In-flight dwell state is per-identity too: a part-read section must not
  // carry over into the next student's session on a shared machine.
  //
  // Dropping the registry is not enough. A tracker still holds its episode map
  // directly, and an armed timer keeps running: it would fire after logout and
  // re-buffer a read for the student who just left, under the key we are in the
  // middle of wiping. So cancel the timers, neutralise any callback already
  // queued, and empty the maps the trackers are holding.
  for (const episodes of EPISODES_BY_SCOPE.values()) {
    for (const ep of episodes.values()) {
      if (ep.timer) clearTimeout(ep.timer)
      ep.timer = null
      ep.fired = true
    }
    episodes.clear()
  }
  EPISODES_BY_SCOPE.clear()
}

/* ─── dwell tracking ─── */

/**
 * Open episodes, keyed by buffer key (i.e. by student + group session) and then
 * by section. Deliberately module level rather than per-tracker.
 *
 * Why: the centre column mounts the artifact pane conditionally, so switching to
 * "My coach" and back UNMOUNTS ArtifactPanel. If episodes lived on the tracker
 * they would die with it, and the accumulated dwell time would be thrown away --
 * while an OS-level tab switch (visibilitychange) merely pauses and preserves
 * it. Two students who each genuinely read a section for 5.8s would then get
 * different read/no-read outcomes purely from which way they navigated away.
 * That is a measurement artifact in the primary research signal, so both routes
 * now behave the same: navigating away PAUSES, it does not discard.
 *
 * Scoped by buffer key so one identity's dwell state is unreachable from
 * another's, same as the event buffer. In-memory only, which is exact parity
 * with the OS case -- a reload clears both.
 */
const EPISODES_BY_SCOPE = new Map()

function episodesFor(key) {
  let m = EPISODES_BY_SCOPE.get(key)
  if (!m) {
    m = new Map()
    EPISODES_BY_SCOPE.set(key, m)
  }
  return m
}

function newEventId() {
  try {
    if (crypto?.randomUUID) return crypto.randomUUID()
  } catch { /* fall through */ }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

/**
 * Tracks one open-episode per section.
 *
 * `send` is called with the event payload when the dwell threshold is crossed.
 * It may fail or no-op (e.g. socket down) -- the event is buffered first, so a
 * failed send is retried on the next flush.
 */
export function createReadTracker({ send, surface, scope, dwellMs = READ_DWELL_MS }) {
  const key = bufferKey(scope)
  // sectionKey -> { eventId, eventType, visibleMs, startedAt, timer, fired }
  // Shared per scope, so it outlives this tracker (see EPISODES_BY_SCOPE).
  const episodes = episodesFor(key)

  function emit(sectionKey, ep) {
    const event = {
      type: 'section_read',
      event_id: ep.eventId,
      section_key: sectionKey,
      event_type: ep.eventType,
      dwell_ms: Math.round(ep.visibleMs),
      client_ts: new Date().toISOString(),
      surface,
    }
    // Buffer BEFORE sending, so a send that never lands is retried rather than lost.
    bufferEvent(key, event)
    try {
      send(event)
    } catch {
      /* stays buffered for the next flush */
    }
  }

  function arm(sectionKey) {
    const ep = episodes.get(sectionKey)
    if (!ep || ep.fired || ep.timer) return
    const remaining = Math.max(0, dwellMs - ep.visibleMs)
    ep.startedAt = Date.now()
    ep.timer = setTimeout(() => {
      const cur = episodes.get(sectionKey)
      if (!cur || cur.fired) return
      cur.visibleMs += Date.now() - cur.startedAt
      cur.timer = null
      cur.fired = true
      emit(sectionKey, cur)
    }, remaining)
  }

  function disarm(sectionKey) {
    const ep = episodes.get(sectionKey)
    if (!ep || !ep.timer) return
    clearTimeout(ep.timer)
    ep.timer = null
    ep.visibleMs += Date.now() - ep.startedAt
  }

  /** Explicit open/expand. The ONLY entry point that starts a timer. */
  function open(sectionKey, eventType = 'section_open') {
    const existing = episodes.get(sectionKey)
    if (existing) {
      // Already read, or already counting: opening again changes nothing. This
      // is what keeps a repeated open from producing a second event.
      if (existing.fired || existing.timer) return
      // A paused episode -- the pane was unmounted or the tab was hidden
      // mid-dwell. Resume it, keeping the time already banked.
      if (!isHidden()) arm(sectionKey)
      return
    }
    episodes.set(sectionKey, {
      eventId: newEventId(),
      eventType,
      visibleMs: 0,
      startedAt: Date.now(),
      timer: null,
      fired: false,
    })
    if (!isHidden()) arm(sectionKey)
  }

  /**
   * Explicitly collapsed. This is the only thing that ENDS an episode: below
   * threshold it discards the accumulated dwell, so a click-through reads as no
   * read at all. Note the asymmetry with detach() -- unmounting the pane is not
   * a collapse and must not be treated as one.
   */
  function close(sectionKey) {
    disarm(sectionKey)
    episodes.delete(sectionKey)
  }

  /** Sections with a live episode, i.e. the ones the student has open. */
  function expandedKeys() {
    return [...episodes.keys()]
  }

  function isHidden() {
    return typeof document !== 'undefined' && document.visibilityState === 'hidden'
  }

  function handleVisibility() {
    if (isHidden()) {
      for (const sk of episodes.keys()) disarm(sk)
    } else {
      for (const sk of episodes.keys()) arm(sk)
    }
  }

  /**
   * Start listening, and resume anything left paused.
   *
   * Registering the listener here rather than at construction is not a style
   * choice. React 18 StrictMode simulates a remount (effect -> cleanup ->
   * effect) on first mount, so a listener added during construction and removed
   * by the cleanup was gone for good while the tracker still looked alive:
   * open/close/timers/buffering all kept working and only the visibility pause
   * silently died -- in dev, which is where the behaviour gets eyeballed. With
   * attach/detach the same sequence ends with a live listener and no change of
   * object identity, so nothing holds a stale tracker.
   */
  function attach() {
    if (typeof document !== 'undefined') {
      // Same function reference, so a double attach cannot double-register.
      document.addEventListener('visibilitychange', handleVisibility)
    }
    // Coming back to the pane is the same event as coming back to the tab.
    if (!isHidden()) for (const sk of episodes.keys()) arm(sk)
  }

  /**
   * Stop listening and pause every open episode, banking the visible time so
   * far. Deliberately NOT a close: the student navigating to another tab in the
   * app is the same act as backgrounding the browser tab, and neither one means
   * they did not read what they had open.
   */
  function detach() {
    for (const sk of episodes.keys()) disarm(sk)
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }

  /** Replay everything still unacked. Called on (re)connect. */
  function flush() {
    for (const event of loadBuffer(key)) {
      try {
        send(event)
      } catch {
        break // socket still down; try again next time
      }
    }
  }

  /**
   * Hard teardown: ends every episode and forgets the scope entirely. This is
   * the "the student is done / logged out" path, not the "navigated away" one.
   * Unmounting a pane must use detach(), or the dwell unification is lost.
   */
  function dispose() {
    for (const sk of [...episodes.keys()]) close(sk)
    detach()
    EPISODES_BY_SCOPE.delete(key)
  }

  return {
    open, close, flush, attach, detach, dispose, expandedKeys,
    ack: (eventId) => ackEvent(key, eventId),
    bufferKey: key,
    _episodes: episodes,
  }
}

/**
 * React hook wrapper. Any component that can display a teammate's section
 * content MUST use this -- `tests/test_read_event_coverage.py` fails the build
 * otherwise, which is what stops a new display surface being added later
 * without read logging.
 */
export function useSectionReadTracking({ send, surface, scope, dwellMs, React }) {
  const { useEffect, useRef } = React
  const ref = useRef(null)
  if (ref.current === null) {
    // Construction is now side-effect free -- no listener, no timer -- so doing
    // it lazily in render is safe. Everything with an effect lives in attach().
    ref.current = createReadTracker({ send, surface, scope, dwellMs })
  }
  useEffect(() => {
    const tracker = ref.current
    tracker.attach()
    // detach, NOT dispose: unmounting this pane pauses the open episodes and
    // keeps their banked time, exactly as hiding the browser tab would. Ending
    // them here is what used to make an in-app tab switch lose dwell that an OS
    // tab switch kept.
    return () => tracker.detach()
  }, [])
  return ref.current
}
