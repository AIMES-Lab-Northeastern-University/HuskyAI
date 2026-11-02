import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { DIM_META } from '../lib/metricInfo'
import { API_URL, authHeaders, clearSession, readApiError } from '../lib/api'
import { StudentSubmissionBar, keepLineBreaks } from '../components/TeamSubmission'
import FinalReview, { wordCount } from '../components/FinalReview'
import { clearAllReadBuffers, createReadSender } from '../lib/readBuffer'
import ScoreNotice, { lateScoreAction } from '../components/ScoreNotice'
import { AttachButton, FileChip, PendingFiles, usePendingFiles } from '../components/Attachments'

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
// Mirrors backend artifacts.MAX_SECTION_CHARS; the server refuses longer saves.
const SECTION_MAX_CHARS = 20000

/* Collaborative-study workspace: this student's PRIVATE coach on the left, the
 * team's shared artifact on the right.
 *
 * The read instrumentation here is the point of the page, not a nicety. Two
 * rules shape the UI and must not be "improved" away:
 *
 *  1. Sections start COLLAPSED. A student has to click to read a teammate's
 *     contribution, which is what makes the expand event mean "a person looked
 *     at this" rather than "this happened to be on screen".
 *  2. A teammate's live edit updates the text but NEVER fires a read event.
 *     Rendering is not reading; counting it would manufacture reads for someone
 *     who never looked.
 */

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() || '').join('') || '?'
}
function colorFor(id = '') {
  const palette = ['#C8102E', '#0D9488', '#7C3AED', '#D97706', '#2563EB', '#DB2777']
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return palette[h % palette.length]
}
function scoreColor(pei) {
  if (pei <= 40) return '#C8102E'
  if (pei <= 65) return '#F97316'
  if (pei <= 80) return '#0D9488'
  return '#16A34A'
}
function fmtClock(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function timeAgo(iso) {
  if (!iso) return 'never'
  const s = Math.floor((Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/* Coach-derived text (#13). Rendered markdown and the raw reply differ in
 * markup and whitespace, so both sides are reduced to their words before a
 * pasted chunk is compared with the student's own coach replies. */
export function normaliseForMatch(s = '') {
  // Words only: markup, punctuation and spacing all differ between the raw
  // reply and what the browser copies from its rendering.
  return s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}
const MIN_COACH_CHUNK = 20

export function isCoachText(text, coachReplies) {
  const t = normaliseForMatch(text)
  if (t.length < MIN_COACH_CHUNK) return false
  return coachReplies.some(r => normaliseForMatch(r).includes(t))
}

/* Where the saved text came from. Copied (the explicit action) outranks pasted;
 * a chunk only counts while it is still in the draft, so text the student
 * inserted and then deleted is not credited to the coach. */
export function originFor(draft, copied, pasted) {
  const d = normaliseForMatch(draft)
  const present = (chunk) => d.includes(normaliseForMatch(chunk))
  if (copied.some(present)) return 'coach_copied'
  if (pasted.some(present)) return 'coach_pasted'
  return 'student_typed'
}

/* ───────────────────────── One artifact section ───────────────────────── */

export function Section({ section, isMine, editorName, onExpand, onCollapse, onSave, conflict, onDismissConflict, justUpdatedBy, saveResult, readOnly, coachReplies = [], insertRequest, onInsertSeen, guide, focusRequest, onFocusSeen, variant }) {
  const page = variant === 'page'
  // Page view: Write / Preview, so a student sees the formatted result before
  // it goes into the document everyone reads.
  const [preview, setPreview] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(section.content || '')
  const [saving, setSaving] = useState(false)
  // The version this draft was started from. It must NOT be read from
  // section.version at save time: a teammate's save updates that live, so a
  // stale draft would claim to be current and overwrite their work unchallenged.
  const [baseVersion, setBaseVersion] = useState(section.version)
  // The text we last sent, so a conflict can hand it back.
  const sentDraft = useRef('')
  // Why the last save did not land (offline, refused by the server). The
  // editor stays open with the draft in it whenever this is set.
  const [saveError, setSaveError] = useState(null)
  // Coach text that entered this draft: by "Copy to document", or pasted.
  const copiedChunks = useRef([])
  const pastedChunks = useRef([])
  // Whether THIS mounted editor has a save waiting for its answer. Answers and
  // conflicts live in the parent, which outlives us: closing the document panel
  // unmounts every section, and on remount the last answer would replay —
  // closing an editor "Copy to document" just opened, or reopening an empty one
  // under an old error. Only answers to our own sends apply.
  const awaitingSave = useRef(false)
  const rootRef = useRef(null)


  // Follow the server's copy while not actively editing, so a teammate's edit
  // lands live instead of being silently overwritten by a stale draft.
  useEffect(() => { if (!editing) setDraft(section.content || '') }, [section.content, section.version, editing])
  // Declared after the effect above so it runs second: on a conflict that effect
  // has just replaced the draft with the teammate's text, and this restores ours.
  useEffect(() => {
    if (!conflict || !awaitingSave.current) return
    awaitingSave.current = false
    setSaving(false)
    setDraft(sentDraft.current)
    setBaseVersion(conflict.version)
    setEditing(true)
  }, [conflict])
  // Declared after the follow effect for the same reason: on a render where
  // both fire, the inserted text must be applied last.
  // "Copy to document" on a coach reply, aimed at this section: open the
  // editor (from the current version, unless a draft is already open) and
  // append the reply for the student to edit before saving. Opening it this
  // way emits no read event: the rule is that only the student's own click
  // on a section is a read.
  useEffect(() => {
    if (!insertRequest || readOnly) return
    setOpen(true)
    if (!editing) setBaseVersion(section.version)
    setEditing(true)
    setDraft(prev => {
      const base = prev || ''
      return base.trim() ? `${base.replace(/\s+$/, '')}\n\n${insertRequest.text}` : insertRequest.text
    })
    copiedChunks.current.push(insertRequest.text)
    // Consumed: cleared in the parent so a later remount cannot apply it again.
    onInsertSeen?.(insertRequest.n)
  }, [insertRequest]) // eslint-disable-line react-hooks/exhaustive-deps

  // "Edit" on the final review: open this section's editor and bring it into
  // view. Not a read event — the review screen already logged that one.
  useEffect(() => {
    if (!focusRequest) return
    setOpen(true)
    if (!readOnly) {
      if (!editing) setBaseVersion(section.version)
      setEditing(true)
    }
    setTimeout(() => rootRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50)
    onFocusSeen?.(focusRequest.n)
  }, [focusRequest]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = () => {
    const next = !open
    setOpen(next)
    // The measurement. Fires only from this click.
    next ? onExpand(section.key) : onCollapse(section.key)
  }

  // The server's answer to our save. The editor closes only on a confirmed
  // write: closing it at send time lost the draft whenever the socket was down
  // or the server refused the write, and left the button stuck on "Saving…".
  useEffect(() => {
    if (!saveResult || !awaitingSave.current) return
    awaitingSave.current = false
    setSaving(false)
    if (saveResult.kind === 'ok') {
      setSaveError(null)
      setEditing(false)
      copiedChunks.current = []
      pastedChunks.current = []
    } else {
      setSaveError(saveResult.message || 'Your save was not accepted.')
      setDraft(sentDraft.current)
      setEditing(true)
    }
  }, [saveResult])

  const save = () => {
    sentDraft.current = draft
    setSaveError(null)
    const origin = originFor(draft, copiedChunks.current, pastedChunks.current)
    const sent = onSave(section.key, draft, baseVersion, origin)
    if (sent === false) {
      setSaveError('Not connected, so nothing was saved. Your draft is still here; save again once you are reconnected.')
      return
    }
    awaitingSave.current = true
    setSaving(true)
  }

  const empty = !(section.content || '').trim()
  const target = guide?.target_words || null
  const words = wordCount(section.content || '')
  const draftWords = wordCount(draft)

  const conflictBox = conflict && (
    <div className="mt-3 p-3 rounded-[10px] bg-[#FDE8EC] border border-[#F5C2CC]" style={{ borderWidth: '1.5px' }}>
      <div className="text-[12px] font-bold text-[#C8102E] mb-1">A teammate saved first</div>
      <div className="text-[12px] text-[#4A4440] mb-2">
        Their version (v{conflict.version}) is below. Your draft was not lost — it is in the editor; fold in their changes and save again.
      </div>
      <div className="mb-2 p-2 rounded-[8px] bg-white border border-[#F5C2CC] text-[12px] text-[#16120E] whitespace-pre-wrap">
        {section.content}
      </div>
      <button onClick={() => onDismissConflict(section.key)}
              className="text-[11px] font-bold text-[#C8102E] underline cursor-pointer">Got it</button>
    </div>
  )

  const editor = (
    <div className="mt-3">
      <textarea
        value={draft}
        onChange={e => setDraft(e.target.value)}
        onPaste={e => {
          // Only the student's OWN coach replies are matched: this
          // page never holds a teammate's private coaching.
          const text = e.clipboardData?.getData('text') || ''
          if (isCoachText(text, coachReplies)) pastedChunks.current.push(text)
        }}
        rows={page ? 14 : 8}
        className={`w-full p-3 text-[#16120E] bg-white border border-[#E7E0D8] rounded-[10px] resize-y leading-relaxed focus:outline-none focus:border-[#C8102E] ${page ? 'text-[14px]' : 'text-[13px] font-mono'}`}
        style={{ borderWidth: '1.5px' }}
        placeholder={guide?.prompt ? `${guide.prompt}\n\nWrite it as the team's finished answer. Discuss in team chat.` : "Write the team's finished answer for this section. Discuss in team chat."}
      />
      <div className={`mt-1 text-right text-[11px] ${draft.length > SECTION_MAX_CHARS ? 'text-[#C8102E] font-bold' : 'text-[#9A948E]'}`}>
        {draftWords}{target ? ` / ~${target}` : ''} words · {draft.length.toLocaleString()} / {SECTION_MAX_CHARS.toLocaleString()} characters
        {draft.length > SECTION_MAX_CHARS && ' · shorten this section to save'}
      </div>
      {saveError && (
        <div role="alert" className="mt-2 text-[12px] text-[#C8102E]">{saveError}</div>
      )}
      <div className="flex gap-2 mt-2">
        <button onClick={save} disabled={saving || draft.length > SECTION_MAX_CHARS}
                className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] hover:bg-[#A50D26] disabled:opacity-50 cursor-pointer">
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button onClick={() => { setEditing(false); setSaving(false); setSaveError(null); setDraft(section.content || ''); copiedChunks.current = []; pastedChunks.current = [] }}
                className="px-3 py-1.5 text-[12px] font-bold text-[#6B6560] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer">
          Cancel
        </button>
      </div>
    </div>
  )

  const view = (
    <div className="mt-3">
      {empty
        ? <div className="text-[13px] text-[#9A948E] italic py-2">Nothing here yet.</div>
        : <div className={`prose-chat text-[#16120E] ${page ? 'text-[15px] leading-relaxed' : 'text-[13px]'}`}><ReactMarkdown remarkPlugins={[remarkGfm]}>{keepLineBreaks(section.content)}</ReactMarkdown></div>}
      {/* A finished session is read-only; the server refuses writes too. */}
      {!readOnly && (
        <button onClick={() => { setBaseVersion(section.version); setEditing(true) }}
                className="mt-3 px-3 py-1.5 text-[12px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] hover:bg-[#EDEAE4] cursor-pointer"
                style={{ borderWidth: '1.5px' }}>
          {empty ? 'Write this section' : 'Edit'}
        </button>
      )}
    </div>
  )

  if (page) {
    return (
      <section ref={rootRef} className="scroll-mt-4">
        <div className="flex items-baseline gap-3 flex-wrap">
          <h2 className="text-[19px] font-bold text-[#16120E] m-0">{section.title || 'Document'}</h2>
          <span className="text-[11px] text-[#9A948E]">
            {empty ? (target ? `Empty · aim for ~${target} words` : 'Empty')
              : `${words}${target ? ` / ~${target}` : ''} words · ${editorName || 'someone'} · ${timeAgo(section.updated_at)}`}
          </span>
          {justUpdatedBy && (
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-[6px] bg-[#FEF3E8] text-[#D97706]">{justUpdatedBy} edited</span>
          )}
        </div>
        {guide?.prompt && <div className="text-[12px] text-[#9A948E] italic mt-1">{guide.prompt}</div>}
        {conflictBox}
        {editing ? (
          <div className="mt-3">
            <div className="flex gap-1 mb-2" role="tablist">
              {[['write', 'Write'], ['preview', 'Preview']].map(([k, label]) => (
                <button key={k} type="button" role="tab" aria-selected={(k === 'preview') === preview}
                        onClick={() => setPreview(k === 'preview')}
                        className={`px-3 py-1 text-[12px] font-bold rounded-[7px] cursor-pointer border ${(k === 'preview') === preview ? 'bg-[#16120E] text-white border-[#16120E]' : 'bg-white text-[#6B6560] border-[#E7E0D8]'}`}>
                  {label}
                </button>
              ))}
              <span className="ml-auto self-center text-[11px] text-[#9A948E] hidden sm:inline">**bold** · - list · 1. numbered · ## heading</span>
            </div>
            {preview ? (
              <>
                <div className="min-h-[200px] p-4 rounded-[10px] border border-[#E7E0D8] bg-[#FDFCFB]">
                  {draft.trim()
                    ? <div className="prose-chat text-[14px] text-[#16120E] leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm]}>{keepLineBreaks(draft)}</ReactMarkdown></div>
                    : <div className="text-[13px] italic text-[#B5AFA8]">Nothing written yet.</div>}
                </div>
                <div className="flex gap-2 mt-2">
                  <button onClick={save} disabled={saving || draft.length > SECTION_MAX_CHARS}
                          className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] hover:bg-[#A50D26] disabled:opacity-50 cursor-pointer">
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button onClick={() => setPreview(false)}
                          className="px-3 py-1.5 text-[12px] font-bold text-[#6B6560] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer">
                    Keep writing
                  </button>
                </div>
                {saveError && <div role="alert" className="mt-2 text-[12px] text-[#C8102E]">{saveError}</div>}
              </>
            ) : editor}
          </div>
        ) : (
          <div className="text-[14px] leading-relaxed">{view}</div>
        )}
      </section>
    )
  }

  return (
    <div ref={rootRef} className="border border-[#E7E0D8] rounded-[12px] bg-[#FDFCFB] overflow-hidden flex-shrink-0" style={{ borderWidth: '1.5px' }}>
      <button
        onClick={toggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-[#F7F3EE] cursor-pointer text-left"
      >
        <svg className={`w-3.5 h-3.5 stroke-[#6B6560] fill-none flex-shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
             viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-bold text-[#16120E] truncate">{section.title || section.key}</div>
          <div className="text-[11px] text-[#9A948E] mt-0.5">
            {empty ? (target ? `Empty · aim for ~${target} words` : 'Empty')
              : `${words}${target ? ` / ~${target}` : ''} words · ${editorName || 'someone'} · ${timeAgo(section.updated_at)}`}
          </div>
        </div>
        {justUpdatedBy && (
          <span className="text-[10px] font-bold px-2 py-1 rounded-[6px] bg-[#FEF3E8] text-[#D97706] flex-shrink-0">
            {justUpdatedBy} edited
          </span>
        )}
        {!open && !empty && (
          <span className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.5px] flex-shrink-0">Click to read</span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-[#E7E0D8]" style={{ borderTopWidth: '1.5px' }}>
          {guide?.prompt && (
            <div className="mt-3 px-3 py-2 rounded-[8px] bg-[#F7F3EE] text-[12px] text-[#4A4440]">
              <span className="font-bold text-[#6B6560]">What goes here: </span>{guide.prompt}
            </div>
          )}
          {conflictBox}

          {editing ? editor : view}
        </div>
      )}
    </div>
  )
}

/* ───────────────────────────── The page ───────────────────────────── */

// Below this width the two panes cannot sit side by side: the artifact pane
// becomes a full-screen overlay opened and closed by its existing toggle.
const NARROW_QUERY = '(max-width: 640px)'

function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia?.(NARROW_QUERY).matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.(NARROW_QUERY)
    if (!mq) return
    const onChange = (e) => setNarrow(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return narrow
}

export default function CoachWorkspace() {
  const navigate = useNavigate()
  const { id: groupId } = useParams()
  const [searchParams] = useSearchParams()
  const sessionNum = searchParams.get('session') || 1

  const token = localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  const myName = user?.name || 'You'
  const narrow = useNarrow()

  const [messages, setMessages]       = useState([])
  const [streaming, setStreaming]     = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isTyping, setIsTyping]       = useState(false)
  const [isEvaluating, setIsEval]     = useState(false)
  const [evalData, setEvalData]       = useState(null)
  const [scoreNotice, setScoreNotice] = useState(null)
  const [turnCount, setTurnCount]     = useState(0)
  const turnCountRef = useRef(0)
  useEffect(() => { turnCountRef.current = turnCount }, [turnCount])
  const [input, setInput]             = useState('')
  const [connStatus, setConn]         = useState('disconnected')
  const [members, setMembers]         = useState([])
  // The whole team, online or not. Presence (`members`) only lists who is
  // connected, so names for edits and the end summary come from here.
  const [roster, setRoster]           = useState([])
  const [challengeTitle, setChTitle]  = useState(null)
  const [challengeContext, setCtx]    = useState(null)
  // The task bar stays pinned above the coach chat for the whole session.
  // null = not toggled yet: expanded until the first message, then collapsed
  // to one line so it doesn't push the conversation down.
  const [taskOpen, setTaskOpen]       = useState(null)
  const [condition, setCondition]     = useState(null)

  const [artifact, setArtifact]       = useState(null)
  // Open by default: this is a two-pane workspace, and a collapsed panel reads
  // as "there is no artifact". Only the SECTIONS start collapsed — that is what
  // makes an expand event mean a person chose to read, and it is preserved here.
  // No artifact_open fires on mount: showing the panel is a render, not a read.
  const [artifactOpen, setArtOpen]    = useState(true)
  const [conflicts, setConflicts]     = useState({})
  // section_key -> { kind: 'ok' | 'error', message?, n } for the last save.
  // `n` makes every answer a new object, so two identical outcomes in a row
  // still reach the Section's effect.
  const [saveResults, setSaveResults] = useState({})
  // { key, text, n } — a "Copy to document" aimed at one section.
  const [insertReq, setInsertReq]     = useState(null)
  const [copyPicker, setCopyPicker]   = useState(null)   // message index choosing a section
  const pendingSaves = useRef(new Set())
  const [teamChat, setTeamChat]       = useState([])
  const [teamInput, setTeamInput]     = useState('')
  const coachFiles = usePendingFiles()
  const teamFiles  = usePendingFiles()
  const [sessionEnded, setEnded]      = useState(false)
  const [ending, setEnding]           = useState(false)
  const [endError, setEndError]       = useState('')
  const [summary, setSummary]         = useState(null)
  // { reason, byName } — why the session ended, for every teammate, not just
  // the one who pressed End.
  const [endInfo, setEndInfo]         = useState(null)
  // Timed sessions: the countdown runs from the server's remaining_seconds.
  // The server decides and enforces the end; this only displays it.
  const [deadlineMs, setDeadlineMs]   = useState(null)
  const [remainingMs, setRemainingMs] = useState(null)
  const [groupSessionId, setGsId]     = useState(null)
  const [inbox, setInbox]             = useState([])
  const [pairs, setPairs]             = useState([])
  const [inboxDirty, setInboxDirty]   = useState(0)
  const [recentEdits, setRecentEdits] = useState({})
  // The instructor's brief and target length per section, by key.
  const [guides, setGuides]           = useState({})
  // Final review: { started_at, required, ready_user_ids, all_ready } from the server.
  const [review, setReview]           = useState(null)
  const [reviewOpen, setReviewOpen]   = useState(false)
  const [reviewNotice, setRevNotice]  = useState('')
  const [readyBusy, setReadyBusy]     = useState(false)
  const [reviewError, setReviewError] = useState('')
  const [focusReq, setFocusReq]       = useState(null)   // { key, n } from the review's Edit
  const [timeLimit, setTimeLimit]     = useState(null)
  // Full-document view: the document takes the main area as pages, the coach
  // shrinks to a side column (or a rail). Off by default, so opening the
  // workspace still shows no teammate's text until someone chooses to read.
  const [docMode, setDocMode]         = useState(false)
  const [coachHidden, setCoachHidden] = useState(false)
  const docReadKeys = useRef(new Set())
  // Team chat can fold down to its header to give the document the height.
  // `seenChat` is how many messages there were when it was folded.
  const [chatOpen, setChatOpen]       = useState(true)
  const [seenChat, setSeenChat]       = useState(0)
  const autoReviewRef = useRef(false)

  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)
  const lastSentRef = useRef('')   // handed back if the server answers busy
  const streamBuf    = useRef('')
  const endRef       = useRef(null)
  const dwellRef     = useRef({})   // clock id -> { started, accumulated, emitDwell }
  const recentTimers = useRef({})
  const teamEndRef   = useRef(null)
  const endedRef     = useRef(false)

  /* Read events, durably.
   *
   * Every read is written to localStorage before it is sent and stays there
   * until the server acks its event_id, then replayed on reconnect with its
   * ORIGINAL client_ts. Two failures this covers that an in-memory queue does
   * not: a send accepted by a socket that is OPEN but already dead (readyState
   * lags a dropped connection by seconds), and the student reloading the page
   * while it looks stuck — which is exactly when unsent reads are being held.
   *
   * Delivery is at-least-once and the server dedupes on the same id, so a
   * replay costs a duplicate frame and never a duplicate row. A read that goes
   * unrecorded cannot be reconstructed from anything else.
   *
   * Scoped per student per session: see readBuffer.bufferKey. */
  const reader = useRef(null)
  if (reader.current === null) {
    reader.current = createReadSender({
      scope: { userId: user?.id, groupSessionId: `${groupId}:${sessionNum}` },
      socket: () => wsRef.current,
    })
  }

  const emit = useCallback((payload) => {
    reader.current.emit(payload)
  }, [])

  const flushOutbox = useCallback(() => {
    reader.current.flush()
  }, [])

  /* Dwell (#17). One clock per open thing: a section, or one contested
   * option. The clock pauses while the tab is hidden (a background tab is not
   * being read), and every open clock is flushed when the page goes away or
   * the session ends, instead of that last interval being lost. `flush` says
   * what closed it (see docs/metrics-codebook.md). */
  const startDwell = useCallback((id, emitDwell) => {
    dwellRef.current[id] = { started: document.hidden ? null : Date.now(), accumulated: 0, emitDwell }
  }, [])

  const stopDwell = useCallback((id, flush) => {
    const d = dwellRef.current[id]
    if (!d) return
    delete dwellRef.current[id]
    const ms = d.accumulated + (d.started != null ? Date.now() - d.started : 0)
    if (ms > 500) d.emitDwell(Math.round(ms), flush)
  }, [])

  const flushAllDwell = useCallback((flush) => {
    for (const id of Object.keys(dwellRef.current)) stopDwell(id, flush)
  }, [stopDwell])

  useEffect(() => {
    const onVisibility = () => {
      const now = Date.now()
      for (const d of Object.values(dwellRef.current)) {
        if (document.hidden) {
          if (d.started != null) { d.accumulated += now - d.started; d.started = null }
        } else if (d.started == null) {
          d.started = now
        }
      }
    }
    // pagehide, not beforeunload: it also fires on mobile tab switches and
    // bfcache navigations. Each emit is written to the durable buffer before
    // it is sent, so a flush the socket cannot deliver now is replayed on the
    // next visit.
    const onPageHide = () => flushAllDwell('pagehide')
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onPageHide)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pagehide', onPageHide)
      flushAllDwell('unmount')
    }
  }, [flushAllDwell])

  const onExpand = useCallback((key) => {
    emit({ type: 'artifact_expand', section_key: key })
    startDwell(`s:${key}`, (ms, flush) =>
      emit({ type: 'artifact_dwell', section_key: key, duration_ms: ms, flush }))
  }, [emit, startDwell])

  const onCollapse = useCallback((key) => {
    stopDwell(`s:${key}`, 'collapse')
  }, [stopDwell])

  /* Contested options (#16) start collapsed, like sections, and opening one
   * is the only thing that counts as inspecting it. The options stay
   * unlabelled: which side came from the coach is never shown. */
  const [openOptions, setOpenOptions] = useState({})
  const toggleOption = useCallback((pairId, option) => {
    const id = `o:${pairId}:${option}`
    const next = !openOptions[id]
    setOpenOptions(prev => ({ ...prev, [id]: next }))
    if (next) {
      emit({ type: 'contested_option_expand', pair_id: pairId, option })
      startDwell(id, (ms, flush) =>
        emit({ type: 'contested_option_dwell', pair_id: pairId, option, duration_ms: ms, flush }))
    } else {
      stopDwell(id, 'collapse')
    }
  }, [openOptions, emit, startDwell, stopDwell])

  /**
   * Emitting happens HERE, not inside the setArtOpen updater.
   *
   * React invokes a state updater twice under StrictMode (and may re-invoke it
   * during a re-render), so an emit inside one fires twice with two different
   * event_ids — which dedupe cannot collapse, because they are genuinely two
   * different events as far as the server can tell. That silently doubled every
   * artifact_open and artifact_close in dev, the build any pilot run is most
   * likely to be served from. The updater is now pure and the event fires once,
   * from the click.
   */
  const togglePanel = useCallback(() => {
    const next = !artifactOpen
    if (!next) {
      // Closing the panel ends any open dwells (sections and options both
      // live in it, and unmount with it).
      flushAllDwell('panel_close')
      setOpenOptions({})
      // Open drafts unmount with the panel, so a conflict about one is moot.
      setConflicts({})
      setDocMode(false)
      setCoachHidden(false)
    }
    setArtOpen(next)
    emit({ type: next ? 'artifact_open' : 'artifact_close' })
  }, [artifactOpen, emit, flushAllDwell])

  const saveCounter = useRef(0)
  const settleSave = useCallback((key, kind, message) => {
    pendingSaves.current.delete(key)
    saveCounter.current += 1
    setSaveResults(prev => ({ ...prev, [key]: { kind, message, n: saveCounter.current } }))
  }, [])

  // Returns false when nothing was sent, so the editor can keep the draft.
  const saveSection = useCallback((key, content, expectedVersion, origin = 'student_typed') => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false
    try {
      wsRef.current.send(JSON.stringify({
        type: 'artifact_write', section_key: key, content,
        expected_version: expectedVersion, origin,
        // Tells the reliance metric this client can detect coach-derived
        // text, so "none adopted" is a real zero rather than a missing signal.
        origin_tracking: 'copy+paste',
      }))
    } catch { return false }
    pendingSaves.current.add(key)
    return true
  }, [])

  const insertCounter = useRef(0)
  const copyToSection = useCallback((key, text) => {
    insertCounter.current += 1
    setInsertReq({ key, text, n: insertCounter.current })
    setCopyPicker(null)
    // The document must be visible to edit in. Opened through the normal
    // toggle, so the open is recorded exactly as if the student clicked it.
    if (!artifactOpen) togglePanel()
  }, [artifactOpen, togglePanel])

  const markRecentEdit = useCallback((key, name) => {
    setRecentEdits(prev => ({ ...prev, [key]: name }))
    clearTimeout(recentTimers.current[key])
    recentTimers.current[key] = setTimeout(
      () => setRecentEdits(prev => { const n = { ...prev }; delete n[key]; return n }), 6000)
  }, [])

  const handleMessage = useCallback((data) => {
    switch (data.type) {
      case 'session_init':
        if (typeof data.turn_count === 'number') setTurnCount(data.turn_count)
        if (data.review) setReview(data.review)
        setTimeLimit(data.time_limit_minutes ?? null)
        if (data.condition) setCondition(data.condition)
        if (data.group_session_id) setGsId(data.group_session_id)
        if (typeof data.remaining_seconds === 'number') {
          setDeadlineMs(Date.now() + data.remaining_seconds * 1000)
          setRemainingMs(data.remaining_seconds * 1000)
        } else {
          setDeadlineMs(null)
          setRemainingMs(null)
        }
        break
      case 'challenge_context': setCtx(data.data); break
      case 'history':
        if (Array.isArray(data.messages)) {
          setMessages(data.messages.filter(m => m?.role && typeof m.content === 'string')
            .map(m => ({
              role: m.role, content: m.content,
              // The history carries each file's bytes, so the chip can open a preview.
              attachments: (m.attachments || []).map(a => ({ name: a.filename || a.name, data: a.data })),
            })))
        }
        if (typeof data.turn_count === 'number') setTurnCount(data.turn_count)
        break
      case 'artifact':
        setArtifact(data.data)
        break
      case 'section_guides':
        setGuides(data.data || {})
        break
      case 'review_state': {
        const { type: _t, started_by_name, reset_by_name, reset_section, ...state } = data
        setReview(state)
        if (started_by_name && started_by_name !== myName) {
          setRevNotice(`${started_by_name} wants to finish. Read the whole document, fix anything flagged, then mark yourself ready.`)
          setReviewOpen(true)
        } else if (reset_by_name) {
          setRevNotice(`${reset_by_name === myName ? 'You' : reset_by_name} changed the document, so everyone's "ready" was cleared. Check the change and mark ready again.`)
        }
        break
      }
      case 'artifact_updated': {
        // A teammate's live edit. Updates the text; deliberately emits nothing.
        setArtifact(prev => prev && ({
          ...prev,
          sections: prev.sections.map(s => s.key === data.section_key
            ? { ...s, content: data.content, version: data.version,
                updated_by_user_id: data.updated_by_user_id, updated_at: new Date().toISOString() }
            : s),
        }))
        markRecentEdit(data.section_key, data.updated_by_name)
        break
      }
      case 'artifact_write_ok':
        // An unchanged save wrote nothing, so the section (including who last
        // edited it) stays exactly as it was.
        if (data.unchanged) {
          setConflicts(prev => { const n = { ...prev }; delete n[data.section_key]; return n })
          settleSave(data.section_key, 'ok')
          break
        }
        // Apply our own saved text. The broadcast that carries content excludes
        // the sender, so without taking it from the ack the author's section
        // would keep rendering as empty.
        setArtifact(prev => prev && ({
          ...prev,
          sections: prev.sections.map(s => s.key === data.section_key
            ? { ...s, content: data.content ?? s.content, version: data.version,
                updated_by_user_id: user?.id, updated_at: new Date().toISOString() }
            : s),
        }))
        setConflicts(prev => { const n = { ...prev }; delete n[data.section_key]; return n })
        settleSave(data.section_key, 'ok')
        break
      case 'artifact_conflict':
        // Their text wins on screen; our draft stays in the editor to rebase.
        pendingSaves.current.delete(data.section_key)
        setConflicts(prev => ({ ...prev, [data.section_key]: { version: data.version } }))
        setArtifact(prev => prev && ({
          ...prev,
          sections: prev.sections.map(s => s.key === data.section_key
            ? { ...s, content: data.content, version: data.version } : s),
        }))
        break
      case 'artifact_error':
        console.error('artifact error:', data.message || data.error)
        // Refused writes carry their section; the editor keeps the draft and
        // says why instead of silently closing.
        if (data.section_key) settleSave(data.section_key, 'error', data.message || data.error)
        break
      case 'typing': setIsTyping(true); setIsStreaming(false); streamBuf.current = ''; setStreaming(''); break
      case 'stream':
        setIsTyping(false); setIsStreaming(true)
        streamBuf.current += data.content
        setStreaming(prev => prev + data.content)
        break
      case 'done':
        setIsStreaming(false); setIsTyping(false)
        setMessages(prev => [...prev, { role: 'assistant', content: data.full_response || streamBuf.current }])
        streamBuf.current = ''; setStreaming('')
        break
      case 'eval_start': setIsEval(true); break
      case 'eval':
        setIsEval(false); setEvalData(data.data); setScoreNotice(null)
        setTurnCount(t => t + 1)
        break
      case 'eval_error': setIsEval(false); break
      case 'eval_pending':
      case 'eval_late':
      case 'eval_rescore_failed': {
        const a = lateScoreAction(data, turnCountRef.current)
        setIsEval(false)
        if (a.countTurn) setTurnCount(t => t + 1)
        if (a.show) setEvalData(a.show)
        setScoreNotice(a.notice)
        break
      }
      case 'presence': if (Array.isArray(data.members)) setMembers(data.members); break
      case 'verification_assigned':
        // A teammate's save was routed to someone; refresh in case it is mine.
        setInboxDirty(n => n + 1)
        break
      case 'team_chat_history':
        if (Array.isArray(data.messages)) {
          setTeamChat(data.messages.map(m => ({
            senderName: m.sender_name, content: m.content, isSelf: m.sender_name === myName,
            attachments: m.attachments || [],
          })))
        }
        break
      case 'team_chat':
        // Human-only backchannel. Never enters a coach prompt or the evaluator;
        // whether it enters the research record at all is an open question, so
        // nothing here emits a study event.
        setTeamChat(prev => [...prev, {
          senderName: data.sender_name, content: data.content, isSelf: false, attachments: data.attachments || [],
        }])
        break
      case 'team_chat_saved':
        // My own message, now stored: swap its placeholder chips for the
        // stored files so they become downloadable.
        setTeamChat(prev => prev.map(m => (m.clientId && m.clientId === data.client_id
          ? { ...m, attachments: [...(data.attachments || []), ...(m.attachments || []).filter(a => a.failed)] }
          : m)))
        break
      case 'team_chat_rejected': {
        const reasons = Object.fromEntries((data.files || []).map(f => [f.name, f.reason]))
        setTeamChat(prev => prev
          .map(m => (m.clientId && m.clientId === data.client_id
            ? { ...m, attachments: (m.attachments || []).map(a => (a.name in reasons ? { ...a, failed: true, reason: reasons[a.name] } : a)) }
            : m))
          // Nothing left of a files-only message: drop the bubble, keep the notice.
          .filter(m => !(m.clientId === data.client_id && !m.content && (m.attachments || []).every(a => a.failed))))
        teamFiles.setNotice(`Not sent: ${(data.files || []).map(f => `${f.name} (${f.reason})`).join(', ')}`)
        break
      }
      case 'attachment_warning': {
        // The server dropped files from my last coach message; mark them.
        const reasons = Object.fromEntries((data.files || []).map(f => [f.name, f.reason]))
        setMessages(prev => {
          const next = [...prev]
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === 'user') {
              next[i] = { ...next[i], attachments: (next[i].attachments || []).map(a => (
                a.name in reasons ? { ...a, failed: true, reason: reasons[a.name] } : a)) }
              break
            }
          }
          return next
        })
        break
      }
      case 'session_ended':
        // Close every open clock now. The server accepts these for a short
        // grace window after the end, because they measure reading done
        // during the session (see _closing_dwell in main.py).
        flushAllDwell('session_end')
        endedRef.current = true
        setEnded(true)
        setReviewOpen(false)
        // The same figures the student who ended it sees. A bare frame (a
        // refused late turn) keeps what is already shown.
        if (data.summary) setSummary(data.summary)
        if (data.end_reason) {
          setEndInfo({ reason: data.end_reason, byName: data.ended_by_name || null })
        }
        break
      case 'busy':
        // This student's coach already has a turn running (another tab, or a
        // double send): nothing was sent, so undo the optimistic message and
        // hand the text back.
        setIsTyping(false)
        setMessages(prev => {
          const i = prev.findLastIndex(m => m.role === 'user')
          return i === -1 ? prev : prev.slice(0, i).concat(prev.slice(i + 1))
        })
        setInput(cur => cur || lastSentRef.current)
        setScoreNotice('Another tab is still waiting for a reply in this chat, so this message was not sent. Try again in a moment.')
        break
      case 'read_ack':
        // The server has this read. Only now is it safe to stop holding it —
        // see readBuffer: until the ack arrives we cannot tell a delivered read
        // from one that went into a socket that was already dead.
        reader.current.ack(data.event_id)
        break
      case 'error':
        setIsStreaming(false); setIsTyping(false); setIsEval(false)
        console.error('Server error:', data.message)
        break
      default: break
    }
  }, [markRecentEdit, settleSave, flushAllDwell, user?.id, myName])

  const connect = useCallback(() => {
    if (!token || !groupId) return
    if (wsRef.current) {
      try { wsRef.current.onclose = null; wsRef.current.close() } catch {}
      wsRef.current = null
    }
    setConn('connecting')
    const ws = new WebSocket(`${WS_BASE}/coach?token=${token}&group_id=${groupId}&session_num=${sessionNum}`)
    wsRef.current = ws
    ws.onopen = () => { setConn('connected'); clearTimeout(reconnectRef.current); flushOutbox() }
    ws.onclose = (e) => {
      if (wsRef.current !== ws) return
      setConn('disconnected'); setIsStreaming(false); setIsTyping(false); setIsEval(false)
      // A save still waiting for its answer may or may not have landed. Keep
      // the draft and say so; saving again is safe, because a write that did
      // land comes back as a conflict carrying the saved text.
      for (const key of [...pendingSaves.current]) {
        settleSave(key, 'error', 'The connection dropped before your save was confirmed. Your draft is still here; save again once you are reconnected.')
      }
      if (e.code === 4001) {
        clearSession()
        // Drop every buffered read on the way out. On a shared machine the next
        // student's socket would otherwise flush what this one left behind, and
        // the server attributes an event to whoever is authenticated — a
        // fabricated read, on the wrong student, in a permanent log.
        clearAllReadBuffers()
        navigate('/login', { replace: true }); return
      }
      if (e.code === 4003 || e.code === 4005) { setConn('error'); return }
      if (endedRef.current) return
      reconnectRef.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => setConn('error')
    ws.onmessage = (e) => { try { handleMessage(JSON.parse(e.data)) } catch {} }
  }, [token, groupId, sessionNum, handleMessage, flushOutbox, navigate, settleSave])

  useEffect(() => {
    if (!token) { navigate('/login', { replace: true }); return }
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      Object.values(recentTimers.current).forEach(clearTimeout)
      if (wsRef.current) { try { wsRef.current.onclose = null; wsRef.current.close() } catch {} ; wsRef.current = null }
    }
  }, [connect, token, navigate])

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, streaming])
  useEffect(() => { teamEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [teamChat])

  const send = useCallback(() => {
    const content = input.trim()
    const files = coachFiles.files
    if ((!content && !files.length) || isStreaming || isTyping || isEvaluating) return
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    lastSentRef.current = content
    setMessages(prev => [...prev, { role: 'user', content, attachments: files.map(f => ({ name: f.name, data: f.data })) }])
    wsRef.current.send(JSON.stringify({ type: 'message', content, attachments: coachFiles.toWire() }))
    setInput('')
    coachFiles.clear()
  }, [input, coachFiles, isStreaming, isTyping, isEvaluating])

  const sendTeamChat = useCallback(() => {
    const content = teamInput.trim()
    const files = teamFiles.files
    if ((!content && !files.length) || wsRef.current?.readyState !== WebSocket.OPEN) return
    // Matches the server's team_chat_saved / team_chat_rejected back to this bubble.
    const clientId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    setTeamChat(prev => [...prev, {
      senderName: myName, content, isSelf: true, clientId, attachments: files.map(f => ({ name: f.name })),
    }])
    wsRef.current.send(JSON.stringify({ type: 'team_chat', content, client_id: clientId, attachments: teamFiles.toWire() }))
    setTeamInput('')
    teamFiles.clear()
  }, [teamInput, teamFiles, myName])

  const startReview = useCallback(async () => {
    setReviewError('')
    try {
      const r = await fetch(`${API_URL}/groups/${groupId}/sessions/${sessionNum}/review`,
        { method: 'POST', headers: authHeaders() })
      if (!r.ok) { setEndError(await readApiError(r, 'Could not start the final review')); return }
      setReview(await r.json())
      setRevNotice('')
      setReviewOpen(true)
    } catch {
      setEndError('Could not reach the server. Try again.')
    }
  }, [groupId, sessionNum])

  const setReady = useCallback(async (ready) => {
    setReadyBusy(true)
    setReviewError('')
    try {
      const r = await fetch(`${API_URL}/groups/${groupId}/sessions/${sessionNum}/ready`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ ready }),
      })
      if (!r.ok) { setReviewError(await readApiError(r, 'Could not save that')); return }
      const d = await r.json()
      if (d.ended) {
        flushAllDwell('session_end')
        if (d.summary) setSummary(d.summary)
        setEndInfo({ reason: d.summary?.end_reason || 'team_ready' })
        endedRef.current = true
        setEnded(true)
        setReviewOpen(false)
      } else {
        setReview(d)
      }
    } catch {
      setReviewError('Could not reach the server. Try again.')
    } finally {
      setReadyBusy(false)
    }
  }, [groupId, sessionNum, flushAllDwell])

  const endSession = useCallback(async () => {
    if (!window.confirm('Submit the document now and end the session for the whole team? Everyone will be disconnected.')) return
    setEnding(true)
    setEndError('')
    try {
      const r = await fetch(`${API_URL}/groups/${groupId}/sessions/${sessionNum}/end`,
        { method: 'POST', headers: authHeaders() })
      // Locked only on success. A refused or failed end used to lock this tab
      // anyway, leaving the student looking at "Session ended" while the
      // session stayed open on the server for everyone else.
      if (!r.ok) { setEndError(await readApiError(r, 'Could not end the session')); return }
      flushAllDwell('session_end')
      const s = await r.json().catch(() => null)
      setSummary(s)
      if (s?.end_reason) setEndInfo(prev => prev || { reason: s.end_reason, byName: myName })
      endedRef.current = true
      setEnded(true)
      setReviewOpen(false)
    } catch (e) {
      console.error('could not end session', e)
      setEndError('Could not reach the server, so the session is still open. Try again.')
    } finally {
      setEnding(false)
    }
  }, [groupId, sessionNum, flushAllDwell, myName])

  // The review shows every section's full text at once, so opening it is a
  // read of each one that has text, marked as such (see artifacts.READ_VIAS).
  useEffect(() => {
    if (!reviewOpen) return
    for (const s of artifact?.sections || []) {
      if ((s.content || '').trim()) emit({ type: 'artifact_expand', section_key: s.key, via: 'review' })
    }
  }, [reviewOpen]) // eslint-disable-line react-hooks/exhaustive-deps

  // Five minutes before a timed session ends, start the review for everyone,
  // so the team finishes the document instead of being cut off mid-edit.
  useEffect(() => {
    if (sessionEnded || autoReviewRef.current || remainingMs == null || !timeLimit || timeLimit < 10) return
    if (remainingMs > 0 && remainingMs <= 5 * 60000) {
      autoReviewRef.current = true
      if (!review?.started_at) {
        startReview().then(() => setRevNotice('Five minutes left. Finish the document and mark yourself ready.'))
      }
    }
  }, [remainingMs, timeLimit, sessionEnded, review, startReview])

  const openDocMode = useCallback(() => {
    if (!artifactOpen) togglePanel()
    docReadKeys.current = new Set()
    setDocMode(true)
  }, [artifactOpen, togglePanel])

  const closeDocMode = useCallback(() => {
    setDocMode(false)
    setCoachHidden(false)
  }, [])

  // The full view puts every section's text on screen, so each one with text
  // is a read, marked via "document" (see artifacts.READ_VIAS). A section a
  // teammate fills in while the view is open is logged when it appears.
  useEffect(() => {
    if (!docMode || !artifactOpen) return
    for (const s of artifact?.sections || []) {
      if ((s.content || '').trim() && !docReadKeys.current.has(s.key)) {
        docReadKeys.current.add(s.key)
        emit({ type: 'artifact_expand', section_key: s.key, via: 'document' })
      }
    }
  }, [docMode, artifactOpen, artifact, emit])

  const editFromReview = useCallback((key) => {
    setReviewOpen(false)
    if (!artifactOpen) togglePanel()
    setFocusReq({ key, n: Date.now() })
  }, [artifactOpen, togglePanel])

  // Countdown tick. Display only: the server ends the session at the deadline
  // (and refuses anything after it) whether or not this tab is open.
  useEffect(() => {
    if (!deadlineMs || sessionEnded) return
    const tick = () => setRemainingMs(deadlineMs - Date.now())
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [deadlineMs, sessionEnded])

  // Team roster and the challenge's title. Plain GETs for display only — they
  // record nothing, and the socket stays the source of everything measured.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const g = await fetch(`${API_URL}/groups/${groupId}`, { headers: authHeaders() })
        if (!g.ok || cancelled) return
        const group = await g.json()
        if (cancelled) return
        if (Array.isArray(group.members)) setRoster(group.members)
        if (!group.challenge_id) return
        const c = await fetch(`${API_URL}/challenges/${group.challenge_id}`, { headers: authHeaders() })
        if (c.ok && !cancelled) setChTitle((await c.json()).title || null)
      } catch (e) {
        console.error('could not load team details', e)
      }
    })()
    return () => { cancelled = true }
  }, [groupId])

  // Review inbox and contested pairs. Polled on change rather than pushed:
  // both are low-frequency, and a dedicated socket message for each would add
  // two more frame types to a handler that already carries the measurement.
  useEffect(() => {
    if (!groupSessionId) return
    let cancelled = false
    ;(async () => {
      try {
        const [iRes, pRes] = await Promise.all([
          fetch(`${API_URL}/verification/inbox/${groupSessionId}`, { headers: authHeaders() }),
          fetch(`${API_URL}/contested/sessions/${groupSessionId}/mine`, { headers: authHeaders() }),
        ])
        if (cancelled) return
        if (iRes.ok) setInbox((await iRes.json()).filter(x => !x.answered))
        if (pRes.ok) setPairs((await pRes.json()).filter(x => !x.answered))
      } catch (e) {
        console.error('could not load review work', e)
      }
    })()
    return () => { cancelled = true }
  }, [groupSessionId, inboxDirty])

  const submitReview = useCallback(async (assignmentId, verdict) => {
    try {
      const r = await fetch(`${API_URL}/verification/${assignmentId}/respond`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ verdict }),
      })
      if (r.ok) setInbox(prev => prev.filter(x => x.assignment_id !== assignmentId))
    } catch (e) { console.error('review failed', e) }
  }, [])

  const adoptOption = useCallback(async (pairId, adopted) => {
    // Close this pair's option clocks first, so their dwell is sent before
    // the choice is recorded.
    stopDwell(`o:${pairId}:a`, 'collapse')
    stopDwell(`o:${pairId}:b`, 'collapse')
    // The server judges inspection and dwell from those socket events, but the
    // choice goes over HTTP; wait for them to be acked or the choice can be
    // recorded first, with no dwell and possibly "uninspected". Bounded, so a
    // dead socket delays the choice rather than blocking it.
    await reader.current.settled((ev) => ev.pair_id === pairId)
    try {
      const r = await fetch(`${API_URL}/contested/pairs/${pairId}/adopt`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ adopted }),
      })
      if (r.ok) setPairs(prev => prev.filter(x => x.pair_id !== pairId))
    } catch (e) { console.error('adopt failed', e) }
  }, [stopDwell])

  const nameFor = (uidStr) => {
    if (uidStr && user?.id === uidStr) return 'You'
    return (members.find(m => m.user_id === uidStr) || roster.find(m => m.user_id === uidStr))?.name
  }

  const coachReplies = messages.filter(m => m.role === 'assistant').map(m => m.content)
  const docWide = docMode && artifactOpen && !narrow
  const pei = evalData?.scores?.PEI ?? 0
  const busy = isStreaming || isTyping || isEvaluating || sessionEnded

  return (
    <div className="h-screen flex flex-col bg-[#F7F3EE]">
      {/* Header */}
      <div className="px-6 py-3 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center gap-4 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
        <button onClick={() => navigate('/challenges')}
                className="text-[12px] font-bold text-[#6B6560] hover:text-[#16120E] cursor-pointer">← Challenges</button>
        <div className="flex-1 min-w-0">
          <div className="text-[14px] font-bold text-[#16120E] truncate">
            {challengeTitle || challengeContext?.title || 'Collaborative session'}
          </div>
          <div className="text-[11px] text-[#9A948E] truncate">
            {/* The study condition is deliberately NOT shown: a student who can
                read their arm or prominence knows what is being measured. */}
            Session {sessionNum}{challengeTitle && challengeContext?.title && !/^session \d+$/i.test(challengeContext.title.trim()) ? `: ${challengeContext.title}` : ''} · Your coach is private to you
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {members.map(m => (
            <div key={m.user_id} title={m.name}
                 className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white"
                 style={{ background: colorFor(m.user_id) }}>
              {initials(m.name)}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-1.5 text-[11px] text-[#9A948E]">
          <div className={`w-1.5 h-1.5 rounded-full ${connStatus === 'connected' ? 'bg-[#16A34A]' : connStatus === 'error' ? 'bg-[#C8102E]' : 'bg-[#D97706]'}`} />
          {connStatus}
        </div>
        {evalData && (
          <div className="text-right">
            <div className="font-serif text-[20px] leading-none" style={{ color: scoreColor(pei) }}>{Math.round(pei)}</div>
            <div className="text-[9px] font-bold text-[#9A948E] uppercase tracking-[0.5px]">Your PEI</div>
          </div>
        )}
        {!sessionEnded && remainingMs != null && (
          <div className={`flex items-center gap-1 px-2 py-1 rounded-[8px] border text-[12px] font-bold tabular-nums ${remainingMs <= 60000 ? 'bg-[#FEF3E8] text-[#C2410C] border-[#FED7AA]' : 'bg-[#F7F3EE] text-[#6B6560] border-[#E7E0D8]'}`}
               title={remainingMs <= 60000 ? 'Session ends soon' : 'Time remaining in this team session'}>
            <span aria-hidden>⏱</span>{fmtClock(remainingMs)}
          </div>
        )}
        {!sessionEnded && endError && (
          <span role="alert" className="text-[12px] text-[#C8102E] max-w-[260px]">{endError}</span>
        )}
        {!sessionEnded && (review?.started_at ? (
          <button onClick={() => { setRevNotice(''); setReviewOpen(true) }}
                  className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#0D9488] rounded-[8px] border-0 cursor-pointer">
            Final review · {review.ready_user_ids?.length || 0}/{review.required?.length || 0} ready
          </button>
        ) : (
          <button onClick={startReview} disabled={ending || connStatus !== 'connected'}
                  className="px-3 py-1.5 text-[12px] font-bold text-[#C8102E] bg-[#FDFCFB] border border-[#E7E0D8] rounded-[8px] hover:bg-[#FDE8EC] disabled:opacity-50 cursor-pointer"
                  style={{ borderWidth: '1.5px' }}
                  title="Review the whole document with your team, then submit it">
            Finish &amp; review
          </button>
        ))}
      </div>

      {sessionEnded && (
        <div className="px-6 py-3 bg-[#E6F7F6] border-b border-[#C7E9E6] flex flex-wrap items-center gap-x-4 gap-y-2 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span className="text-[13px] font-bold text-[#0D9488]">
            {endInfo?.reason === 'timer_expired' ? 'Time is up — session ended.'
              : endInfo?.reason === 'team_ready' ? 'Everyone marked the document ready — submitted.'
              : endInfo?.byName ? `Session ended by ${endInfo.byName}.`
              : 'Session ended.'}
          </span>
          {summary && (
            <span className="text-[12px] text-[#4A4440]">
              Team mean PEI {summary.session_avg_pei ?? '—'} across {summary.turns} turn{summary.turns === 1 ? '' : 's'}
              {summary.per_student && Object.keys(summary.per_student).length > 1 && (
                <> · {Object.entries(summary.per_student)
                  .map(([uidStr, v]) => `${v.name || nameFor(uidStr) || 'member'}: ${v.avg_pei ?? '—'} (${v.turns} turn${v.turns === 1 ? '' : 's'})`)
                  .join(' · ')}</>
              )}
            </span>
          )}
          <StudentSubmissionBar groupId={groupId} sessionNum={sessionNum} />
          <button onClick={() => navigate('/challenges')}
                  className="ml-auto text-[12px] font-bold text-[#0D9488] underline cursor-pointer">
            Back to challenges
          </button>
        </div>
      )}

      {reviewOpen && !sessionEnded && artifact && (
        <FinalReview
          sections={artifact.sections || []}
          guides={guides}
          review={review}
          myId={user?.id}
          nameFor={nameFor}
          teamNames={roster.map(m => m.name)}
          notice={reviewNotice}
          onClose={() => setReviewOpen(false)}
          onEdit={editFromReview}
          onReady={setReady}
          readyBusy={readyBusy}
          onSubmitNow={endSession}
          ending={ending}
          error={reviewError || endError}
        />
      )}

      {connStatus === 'error' && (
        <div className="px-6 py-2 bg-[#FDE8EC] text-[12px] text-[#C8102E] font-bold flex-shrink-0">
          Could not join this session — you may not be a member of this team, or the assignment's artifact is misconfigured.
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* ── Private coach ── */}
        {docWide && coachHidden && (
          <div className="h-full flex flex-col items-center py-4 gap-3 bg-[#FDFCFB] border-r border-[#E7E0D8] flex-shrink-0" style={{ width: 52, borderRightWidth: '1.5px' }}>
            <button onClick={() => setCoachHidden(false)} title="Show your coach" aria-label="Show your coach"
                    className="w-8 h-8 rounded-[8px] bg-[#F7F3EE] hover:bg-[#EDEAE4] border border-[#E7E0D8] flex items-center justify-center cursor-pointer"
                    style={{ borderWidth: '1.5px' }}>
              <svg className="w-4 h-4 stroke-[#6B6560] fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
            </button>
            <div className="flex-1" />
            <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.7px]"
                 style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
              Your coach
            </div>
          </div>
        )}
        {/* Kept mounted while hidden, so the chat and any reply in progress survive. */}
        <div className={`${docWide ? 'flex-shrink-0' : 'flex-1'} ${docWide && coachHidden ? 'hidden' : 'flex'} flex-col min-w-0 border-r border-[#E7E0D8]`}
             style={{ borderRightWidth: '1.5px', width: docWide ? 400 : undefined }}>
          <div className="px-5 py-2.5 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center gap-2 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
            <span className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Your private coach</span>
            <span className="text-[10px] text-[#9A948E]">· teammates cannot see this</span>
            {turnCount > 0 && <span className="text-[11px] text-[#9A948E] ml-auto">Turn {turnCount}</span>}
            {docWide && (
              <button onClick={() => setCoachHidden(true)} title="Hide your coach to give the document more room"
                      className={`${turnCount > 0 ? '' : 'ml-auto'} text-[11px] font-bold text-[#6B6560] underline cursor-pointer bg-transparent border-0`}>
                Hide
              </button>
            )}
          </div>

          {challengeContext && (challengeContext.goal || challengeContext.brief || challengeContext.seed_question) && (() => {
            const open = taskOpen ?? messages.length === 0
            return (
              <div className="px-5 py-3 bg-[#FDFCFB] border-b border-[#E7E0D8] flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
                <button type="button" onClick={() => setTaskOpen(!open)} aria-expanded={open}
                  className="w-full flex items-center gap-2 text-left bg-transparent border-0 p-0 cursor-pointer">
                  <span className="text-[11px] font-bold text-[#C8102E] uppercase tracking-[0.7px] flex-shrink-0">Task</span>
                  <span className={`text-[13px] text-[#16120E] font-semibold min-w-0 ${open ? '' : 'truncate'}`}>
                    {challengeContext.title}{!open && challengeContext.goal ? ` · ${challengeContext.goal}` : ''}
                  </span>
                  <span className="text-[11px] text-[#9A948E] ml-auto flex-shrink-0">{open ? 'Hide' : 'Show'}</span>
                </button>
                {open && (
                  <div className="mt-2 flex flex-col gap-1.5 text-[13px] leading-relaxed">
                    {challengeContext.goal && (
                      <div className="text-[#4A4440]"><strong className="text-[#16120E]">Goal:</strong> {challengeContext.goal}</div>
                    )}
                    {challengeContext.brief && <div className="text-[#4A4440]">{challengeContext.brief}</div>}
                    {challengeContext.seed_question && (
                      <div className="text-[#6B6560] italic">Starter question: {challengeContext.seed_question}</div>
                    )}
                  </div>
                )}
              </div>
            )
          })()}

          <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] px-4 py-2.5 rounded-[14px] text-[14px] leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-[#C8102E] text-white'
                    : 'bg-[#FDFCFB] text-[#16120E] border border-[#E7E0D8]'}`}
                     style={m.role === 'user' ? {} : { borderWidth: '1.5px' }}>
                  {m.attachments?.length > 0 && (
                    <div className={`flex flex-wrap gap-1.5 ${m.content ? 'mb-1.5' : ''}`}>
                      {m.attachments.map((a, j) => <FileChip key={j} file={a} tone={m.role === 'user' ? 'dark' : 'light'} />)}
                    </div>
                  )}
                  {m.role === 'user'
                    ? (m.content && <p className="whitespace-pre-wrap">{m.content}</p>)
                    : <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>}
                  {m.role === 'assistant' && !sessionEnded && artifact?.sections?.length > 0 && (
                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      {copyPicker === i ? (
                        <>
                          <span className="text-[11px] text-[#9A948E]">Copy into:</span>
                          {artifact.sections.map(s => (
                            <button key={s.key} onClick={() => copyToSection(s.key, m.content)}
                                    className="px-2 py-0.5 text-[11px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[6px] cursor-pointer">
                              {s.title || s.key}
                            </button>
                          ))}
                          <button onClick={() => setCopyPicker(null)}
                                  className="text-[11px] text-[#9A948E] underline cursor-pointer">Cancel</button>
                        </>
                      ) : (
                        <button onClick={() => artifact.sections.length === 1
                                            ? copyToSection(artifact.sections[0].key, m.content)
                                            : setCopyPicker(i)}
                                className="text-[11px] font-bold text-[#6B6560] hover:text-[#16120E] underline cursor-pointer">
                          Copy to document
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {isTyping && <div className="text-[12px] text-[#9A948E]">Coach is thinking…</div>}
            {isStreaming && (
              <div className="flex justify-start">
                <div className="max-w-[80%] px-4 py-2.5 rounded-[14px] bg-[#FDFCFB] border border-[#E7E0D8] text-[14px]" style={{ borderWidth: '1.5px' }}>
                  <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{streaming}</ReactMarkdown></div>
                </div>
              </div>
            )}
            {isEvaluating && <div className="text-[12px] text-[#9A948E]">Scoring your turn…</div>}
            <ScoreNotice message={scoreNotice} />
            <div ref={endRef} />
          </div>

          <div className="p-4 bg-[#FDFCFB] border-t border-[#E7E0D8] flex-shrink-0" style={{ borderTopWidth: '1.5px' }}>
            <PendingFiles files={coachFiles.files} onRemove={coachFiles.remove} notice={coachFiles.notice} />
            <div className="flex gap-2">
              <AttachButton onFiles={coachFiles.add} disabled={busy || connStatus !== 'connected'}
                            label="Attach a file for your coach" />
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                rows={1}
                placeholder={busy ? 'Waiting for your coach…' : 'Ask your coach…'}
                disabled={busy || connStatus !== 'connected'}
                className="flex-1 px-4 py-2.5 text-[14px] bg-white border border-[#E7E0D8] rounded-[12px] resize-none focus:outline-none focus:border-[#C8102E] disabled:opacity-60"
                style={{ borderWidth: '1.5px' }}
              />
              <button onClick={send} disabled={busy || (!input.trim() && !coachFiles.files.length) || connStatus !== 'connected'}
                      className="px-4 py-2.5 text-[13px] font-bold text-white bg-[#C8102E] rounded-[12px] hover:bg-[#A50D26] disabled:opacity-40 cursor-pointer">
                Send
              </button>
            </div>
          </div>
        </div>

        {/* ── Shared artifact ── */}
        {/* On a phone the open pane covers the screen instead of squeezing the
            coach column to nothing; the same toggle opens and closes it, so the
            open/close events are exactly those of the desktop panel. */}
        <div className={`flex flex-col bg-[#F7F3EE] ${docWide ? 'flex-1 min-w-0' : 'flex-shrink-0'} ${narrow && artifactOpen ? 'fixed inset-0 z-40' : ''}`}
             style={{ width: narrow && artifactOpen ? '100%' : docWide ? undefined : artifactOpen ? 460 : 52 }}>
          {!artifactOpen ? (
            <div className="h-full flex flex-col items-center py-4 gap-3 bg-[#FDFCFB] border-l border-[#E7E0D8]" style={{ borderLeftWidth: '1.5px' }}>
              <button onClick={togglePanel} title="Open shared artifact" aria-label="Open shared artifact"
                      className="w-8 h-8 rounded-[8px] bg-[#F7F3EE] hover:bg-[#EDEAE4] border border-[#E7E0D8] flex items-center justify-center cursor-pointer"
                      style={{ borderWidth: '1.5px' }}>
                <svg className="w-4 h-4 stroke-[#6B6560] fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
              </button>
              {Object.keys(recentEdits).length > 0 && <div className="w-2 h-2 rounded-full bg-[#D97706]" />}
              <div className="flex-1" />
              <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.7px]"
                   style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
                Shared Artifact
              </div>
            </div>
          ) : (
            <div className="h-full flex flex-col bg-[#FDFCFB] border-l border-[#E7E0D8]" style={{ borderLeftWidth: '1.5px' }}>
              <div className="px-4 py-3 border-b border-[#E7E0D8] flex items-center gap-2 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
                <button onClick={togglePanel} title="Close shared artifact"
                        className="w-7 h-7 rounded-[8px] bg-[#F7F3EE] hover:bg-[#EDEAE4] border border-[#E7E0D8] flex items-center justify-center cursor-pointer flex-shrink-0"
                        style={{ borderWidth: '1.5px' }}>
                  <svg className="w-3.5 h-3.5 stroke-[#6B6560] fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
                </button>
                <div className="min-w-0">
                  <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">{docMode ? 'Team document' : 'Shared Artifact'}</div>
                  {!narrow && <div className="text-[11px] text-[#9A948E] mt-0.5">Your team's final answer — this is what your instructor receives</div>}
                </div>
                <button onClick={docMode ? closeDocMode : openDocMode}
                        title={docMode ? 'Back to the side panel' : 'Open the whole document as pages'}
                        className={`${narrow ? '' : 'ml-auto'} px-2.5 py-1.5 text-[11px] font-bold rounded-[8px] cursor-pointer flex-shrink-0 border ${docMode ? 'text-[#4A4440] bg-[#F7F3EE] border-[#E7E0D8]' : 'text-white bg-[#16120E] border-[#16120E]'}`}>
                  {docMode ? 'Exit full view' : '⤢ Full document'}
                </button>
                {/* On a phone this pane covers the header, so finishing lives here too. */}
                {narrow && !sessionEnded && (
                  <button onClick={() => (review?.started_at ? (setRevNotice(''), setReviewOpen(true)) : startReview())}
                          className="ml-auto px-2.5 py-1.5 text-[11px] font-bold text-white bg-[#0D9488] rounded-[8px] border-0 cursor-pointer flex-shrink-0">
                    {review?.started_at ? `Review · ${review.ready_user_ids?.length || 0}/${review.required?.length || 0}` : 'Finish & review'}
                  </button>
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 min-h-0">
                {/* Contested input (Phase 4). Shown before the artifact because
                    it is a decision the student owes, not reference material.
                    The two options are deliberately unlabelled — saying which
                    came from the coach would measure trust in the label. */}
                {pairs.map(p => (
                  <div key={p.pair_id} className="border border-[#D8B4FE] rounded-[12px] bg-[#FAF5FF] p-4 flex-shrink-0"
                       style={{ borderWidth: '1.5px' }}>
                    <div className="text-[11px] font-bold text-[#7C3AED] uppercase tracking-[0.7px] mb-1">
                      Two answers disagree
                    </div>
                    <div className="text-[12px] text-[#6B6560] mb-3">
                      Section “{p.subproblem_key}”. Which do you go with?
                    </div>
                    {[['a', p.option_a], ['b', p.option_b]].map(([k, text]) => {
                      const isOpen = !!openOptions[`o:${p.pair_id}:${k}`]
                      return (
                      <div key={k} className="mb-2 p-3 rounded-[10px] bg-white border border-[#E7E0D8]"
                           style={{ borderWidth: '1.5px' }}>
                        <button onClick={() => toggleOption(p.pair_id, k)}
                                aria-expanded={isOpen}
                                className="w-full flex items-center gap-2 text-left cursor-pointer mb-2">
                          <svg className={`w-3 h-3 stroke-[#7C3AED] fill-none flex-shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                               viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
                          <span className="text-[12px] font-bold text-[#16120E]">Option {k.toUpperCase()}</span>
                          {!isOpen && <span className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.5px] ml-auto">Click to read</span>}
                        </button>
                        {isOpen && <div className="text-[13px] text-[#16120E] whitespace-pre-wrap mb-2">{text}</div>}
                        <button onClick={() => adoptOption(p.pair_id, k)}
                                className="px-3 py-1 text-[12px] font-bold text-white bg-[#7C3AED] rounded-[8px] cursor-pointer">
                          Use this one
                        </button>
                      </div>
                      )
                    })}
                    <div className="flex gap-2 mt-1">
                      <button onClick={() => adoptOption(p.pair_id, 'merged')}
                              className="px-3 py-1 text-[12px] font-bold text-[#7C3AED] bg-white border border-[#D8B4FE] rounded-[8px] cursor-pointer"
                              style={{ borderWidth: '1.5px' }}>Combine both</button>
                      <button onClick={() => adoptOption(p.pair_id, 'neither')}
                              className="px-3 py-1 text-[12px] font-bold text-[#6B6560] bg-white border border-[#E7E0D8] rounded-[8px] cursor-pointer"
                              style={{ borderWidth: '1.5px' }}>Neither</button>
                    </div>
                  </div>
                ))}

                {/* Review inbox (Phase 5). Whether the reviewer actually reads
                    the work is measured from their section reads, not from a
                    checkbox here — so there deliberately isn't one. */}
                {inbox.map(item => (
                  <div key={item.assignment_id} className="border border-[#FDBA74] rounded-[12px] bg-[#FFF7ED] p-4 flex-shrink-0"
                       style={{ borderWidth: '1.5px' }}>
                    <div className="text-[11px] font-bold text-[#D97706] uppercase tracking-[0.7px] mb-1">
                      Review a teammate's work
                    </div>
                    <div className="text-[12px] text-[#6B6560] mb-2">
                      Section “{item.section_key}”, v{item.version}
                    </div>
                    <div className="p-3 rounded-[10px] bg-white border border-[#E7E0D8] text-[13px] text-[#16120E] whitespace-pre-wrap mb-3"
                         style={{ borderWidth: '1.5px' }}>
                      {item.content || <span className="italic text-[#9A948E]">Empty</span>}
                    </div>
                    <div className="flex gap-2">
                      {[['correct', 'Looks right', '#16A34A'],
                        ['incorrect', 'Has a problem', '#C8102E'],
                        ['unsure', 'Not sure', '#6B6560']].map(([v, label, col]) => (
                        <button key={v} onClick={() => submitReview(item.assignment_id, v)}
                                className="px-3 py-1.5 text-[12px] font-bold rounded-[8px] bg-white cursor-pointer"
                                style={{ color: col, border: `1.5px solid ${col}40` }}>
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}

                {!artifact && <div className="text-[13px] text-[#9A948E]">Loading…</div>}
                {docMode && artifact && (() => {
                  const secs = artifact.sections || []
                  const total = secs.reduce((n, s) => n + wordCount(s.content || ''), 0)
                  const done = secs.filter(s => (s.content || '').trim()).length
                  return (
                    <div className="w-full max-w-[800px] mx-auto flex-shrink-0">
                      <div className="flex flex-wrap items-center gap-1.5 mb-3">
                        {secs.map(s => {
                          const filled = !!(s.content || '').trim()
                          return (
                            <button key={s.key} type="button"
                                    onClick={() => document.getElementById(`doc-sec-${s.key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-white border border-[#E7E0D8] text-[#4A4440] cursor-pointer hover:bg-[#F7F3EE]">
                              <span className="w-1.5 h-1.5 rounded-full" style={{ background: filled ? '#0D9488' : '#D6CFC7' }} />
                              {s.title || 'Document'}
                            </button>
                          )
                        })}
                        <span className="ml-auto text-[11px] text-[#9A948E]">{done}/{secs.length} sections written · {total} words</span>
                      </div>
                      <div className="bg-white rounded-[14px] border border-[#E7E0D8] px-6 sm:px-10 py-8 flex flex-col gap-9"
                           style={{ borderWidth: '1.5px', boxShadow: '0 1px 3px rgba(22,18,14,0.05)' }}>
                        <header className="border-b border-[#EFE8DF] pb-5">
                          <div className="text-[11px] font-bold text-[#C8102E] uppercase tracking-[0.8px]">Team document</div>
                          <h1 className="text-[24px] font-bold text-[#16120E] leading-tight mt-1 mb-0">{challengeTitle || challengeContext?.title || 'Collaborative session'}</h1>
                          <div className="text-[13px] text-[#6B6560] mt-1">
                            Session {sessionNum}{challengeContext?.title && challengeContext.title !== challengeTitle ? `: ${challengeContext.title}` : ''}
                            {roster.length > 0 && <> · {roster.map(m => m.name).join(', ')}</>}
                          </div>
                        </header>
                        {secs.map(s => (
                          <div key={s.key} id={`doc-sec-${s.key}`} className="scroll-mt-4">
                            <Section
                              variant="page"
                              section={s}
                              isMine={s.updated_by_user_id === user?.id}
                              editorName={nameFor(s.updated_by_user_id)}
                              onExpand={onExpand}
                              onCollapse={onCollapse}
                              onSave={saveSection}
                              conflict={conflicts[s.key]}
                              onDismissConflict={(k) => setConflicts(p => { const n = { ...p }; delete n[k]; return n })}
                              justUpdatedBy={recentEdits[s.key]}
                              saveResult={saveResults[s.key]}
                              readOnly={sessionEnded}
                              coachReplies={coachReplies}
                              insertRequest={insertReq?.key === s.key ? insertReq : null}
                              onInsertSeen={(n) => setInsertReq(r => (r && r.n === n ? null : r))}
                              guide={guides[s.key]}
                              focusRequest={focusReq?.key === s.key ? focusReq : null}
                              onFocusSeen={(n) => setFocusReq(r => (r && r.n === n ? null : r))}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                })()}
                {!docMode && artifact?.sections?.map(s => (
                  <Section
                    key={s.key}
                    section={s}
                    isMine={s.updated_by_user_id === user?.id}
                    editorName={nameFor(s.updated_by_user_id)}
                    onExpand={onExpand}
                    onCollapse={onCollapse}
                    onSave={saveSection}
                    conflict={conflicts[s.key]}
                    onDismissConflict={(k) => setConflicts(p => { const n = { ...p }; delete n[k]; return n })}
                    justUpdatedBy={recentEdits[s.key]}
                    saveResult={saveResults[s.key]}
                    readOnly={sessionEnded}
                    coachReplies={coachReplies}
                    insertRequest={insertReq?.key === s.key ? insertReq : null}
                    onInsertSeen={(n) => setInsertReq(r => (r && r.n === n ? null : r))}
                    guide={guides[s.key]}
                    focusRequest={focusReq?.key === s.key ? focusReq : null}
                    onFocusSeen={(n) => setFocusReq(r => (r && r.n === n ? null : r))}
                  />
                ))}
              </div>

              {/* Team backchannel: student-to-student only. Firewalled by design
                  from the coach prompt and the evaluator. Whether it enters the
                  research record is the assignment's team_chat_logging setting
                  (off | metadata | content, delivered in session_init's
                  condition), so the header says so rather than implying privacy
                  when it is logged. Messages are persisted in
                  group_chat_messages either way. */}
              <div className="border-t border-[#E7E0D8] flex flex-col flex-shrink-0" style={{ borderTopWidth: '1.5px', height: chatOpen ? 240 : 'auto' }}>
                <div className="px-4 py-2 flex items-center gap-2 flex-shrink-0">
                  <span className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Team chat</span>
                  {!chatOpen && teamChat.length > seenChat && (
                    <span className="text-[10px] font-bold text-white bg-[#7C3AED] rounded-full px-1.5">{teamChat.length - seenChat} new</span>
                  )}
                  <span className="text-[10px] text-[#9A948E]">
                    · not seen by any coach{condition?.team_chat_logging === 'content'
                      ? ' · recorded for research'
                      : condition?.team_chat_logging === 'metadata'
                        ? ' · timing logged for research, not text'
                        : ''}
                  </span>
                  <button type="button" onClick={() => { if (chatOpen) setSeenChat(teamChat.length); setChatOpen(!chatOpen) }}
                          aria-expanded={chatOpen}
                          className="ml-auto text-[11px] font-bold text-[#6B6560] underline cursor-pointer bg-transparent border-0 flex-shrink-0">
                    {chatOpen ? 'Hide' : 'Show'}
                  </button>
                </div>
                {chatOpen && (<>
                <div className="flex-1 overflow-y-auto px-4 pb-2 flex flex-col gap-2">
                  {teamChat.length === 0 && (
                    <div className="text-[12px] text-[#9A948E] italic">Talk to your teammates here.</div>
                  )}
                  {teamChat.map((m, i) => (
                    <div key={i} className={`flex ${m.isSelf ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] px-3 py-1.5 rounded-[10px] text-[12px] ${
                        m.isSelf ? 'bg-[#EDE9FE] text-[#16120E]' : 'bg-[#F7F3EE] text-[#16120E]'}`}>
                        {!m.isSelf && <div className="text-[10px] font-bold text-[#6B6560] mb-0.5">{m.senderName}</div>}
                        {m.attachments?.length > 0 && (
                          <div className={`flex flex-wrap gap-1 ${m.content ? 'mb-1' : ''}`}>
                            {m.attachments.map((a, j) => <FileChip key={a.id || j} file={a} groupId={groupId} />)}
                          </div>
                        )}
                        {m.content && <span className="whitespace-pre-wrap">{m.content}</span>}
                      </div>
                    </div>
                  ))}
                  <div ref={teamEndRef} />
                </div>
                {(teamFiles.files.length > 0 || teamFiles.notice) && (
                  <div className="px-3 pt-2 flex-shrink-0">
                    <PendingFiles files={teamFiles.files} onRemove={teamFiles.remove} notice={teamFiles.notice} />
                  </div>
                )}
                <div className="p-3 flex gap-2 flex-shrink-0">
                  <AttachButton onFiles={teamFiles.add} disabled={sessionEnded || connStatus !== 'connected'}
                                label="Share a file with your team" compact />
                  <input
                    value={teamInput}
                    onChange={e => setTeamInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); sendTeamChat() } }}
                    placeholder="Message your team…"
                    disabled={sessionEnded || connStatus !== 'connected'}
                    className="flex-1 px-3 py-1.5 text-[12px] bg-white border border-[#E7E0D8] rounded-[8px] focus:outline-none focus:border-[#7C3AED] disabled:opacity-60"
                    style={{ borderWidth: '1.5px' }}
                  />
                  <button onClick={sendTeamChat} disabled={sessionEnded || (!teamInput.trim() && !teamFiles.files.length) || connStatus !== 'connected'}
                          className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#7C3AED] rounded-[8px] disabled:opacity-40 cursor-pointer">
                    Send
                  </button>
                </div>
                </>)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
