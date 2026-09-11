import { useEffect, useRef, useState } from 'react'
import { useSectionReadTracking } from '../lib/readTracking'

/**
 * The team's shared artifact: fixed sections, one per subproblem.
 *
 * Read logging: a section's content is rendered ONLY while expanded, and the
 * dwell timer starts in the explicit toggle handler -- never on mount or on
 * render. Collapsing before the threshold discards the episode, so an accidental
 * click-through produces no event.
 *
 * This component displays teammates' section content, so it must use
 * useSectionReadTracking. backend/tests/test_read_event_coverage.py enforces
 * that for every surface capable of showing section content.
 */
export const SURFACE = 'artifact_panel'

function LockBadge({ lock, meId }) {
  if (!lock) return null
  const mine = lock.holder_user_id === meId
  return (
    <span
      className="text-[10px] font-bold px-[8px] py-[2px] rounded-[20px] ml-2"
      style={{
        background: mine ? '#DCFCE7' : '#FEF3E8',
        color: mine ? '#16A34A' : '#D97706',
      }}
    >
      {mine ? 'You are editing' : `${lock.holder_name} is editing`}
    </span>
  )
}

export default function ArtifactPanel({
  sections,
  locks,
  meId,
  groupSessionId,
  send,
  onRequestLock,
  onReleaseLock,
  onWrite,
  onTracker,
}) {
  const [drafts, setDrafts] = useState({})

  const tracker = useSectionReadTracking({
    send,
    surface: SURFACE,
    // Scoped so one student's unacked reads can never be replayed under
    // another student's identity on a shared machine.
    scope: { userId: meId, groupSessionId },
    React: { useEffect, useRef },
  })

  // Which sections are open is tracker state, not component state, because this
  // pane is unmounted whenever the centre column shows another tab. Seeding
  // from the tracker is what makes a tab switch equivalent to hiding the
  // browser tab: the student comes back to the section still open and its dwell
  // still counting, instead of a collapsed section and a discarded episode.
  const [expanded, setExpanded] = useState(() => new Set(tracker.expandedKeys()))

  // Hand the tracker up so the socket owner can apply server acks. Without
  // this the ack handlers are no-ops, the localStorage buffer is never pruned,
  // and every reconnect replays every read the student has ever produced.
  useEffect(() => {
    onTracker?.(tracker)
  }, [onTracker, tracker])

  // Replay anything still unacked whenever the socket comes back.
  useEffect(() => {
    if (send) tracker.flush()
  }, [send, tracker])

  const lockFor = (key) => locks.find((l) => l.section_key === key) || null

  /**
   * The only place a read timer starts. Explicit user interaction, not render.
   */
  const toggle = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
        tracker.close(key)          // below threshold -> no event, by design
      } else {
        next.add(key)
        tracker.open(key, 'section_expand')
      }
      return next
    })
  }

  const startEditing = (key) => {
    onRequestLock(key)
  }

  const saveSection = (key) => {
    onWrite(key, drafts[key] ?? '')
    onReleaseLock(key)
  }

  if (!sections?.length) return null

  return (
    <div className="border-t border-[#E7E0D8] bg-[#FDFCFB]" style={{ borderTopWidth: '1.5px' }}>
      <div className="px-5 py-3 text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">
        Shared Artifact
      </div>
      {sections.map((sec) => {
        const isOpen = expanded.has(sec.key)
        const lock = lockFor(sec.key)
        const iHoldIt = lock?.holder_user_id === meId
        return (
          <div key={sec.key} className="border-t border-[#E7E0D8] px-5 py-3">
            <button
              type="button"
              onClick={() => toggle(sec.key)}
              className="flex items-center w-full text-left"
            >
              <span className="text-[13px] font-semibold text-[#16120E]">{sec.title}</span>
              <LockBadge lock={lock} meId={meId} />
              <span className="ml-auto text-[11px] text-[#9A948E]">
                {isOpen ? 'Hide' : 'Show'}
              </span>
            </button>

            {sec.carried_from_session_number != null && sec.version === 0 && (
              <div className="text-[11px] text-[#9A948E] mt-1">
                Carried over from Session {sec.carried_from_session_number}
              </div>
            )}

            {/* Content is mounted only while expanded: it cannot be on screen
                without the student having explicitly opened it. */}
            {isOpen && (
              <div className="mt-2">
                {iHoldIt ? (
                  <>
                    <textarea
                      value={drafts[sec.key] ?? sec.content ?? ''}
                      onChange={(e) =>
                        setDrafts((d) => ({ ...d, [sec.key]: e.target.value }))
                      }
                      className="w-full text-[13px] p-2 border border-[#E7E0D8] rounded-[8px]"
                      rows={6}
                    />
                    <button
                      type="button"
                      onClick={() => saveSection(sec.key)}
                      className="mt-2 text-[12px] font-semibold px-3 py-1.5 rounded-[8px] bg-[#C8102E] text-white"
                    >
                      Save &amp; release
                    </button>
                  </>
                ) : (
                  <>
                    <div className="text-[13px] text-[#4A4440] whitespace-pre-wrap">
                      {sec.content || <em className="text-[#9A948E]">Empty</em>}
                    </div>
                    <button
                      type="button"
                      onClick={() => startEditing(sec.key)}
                      disabled={!!lock}
                      className="mt-2 text-[12px] font-semibold px-3 py-1.5 rounded-[8px] border border-[#E7E0D8] disabled:opacity-40"
                    >
                      {lock ? `Locked by ${lock.holder_name}` : 'Edit this section'}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
