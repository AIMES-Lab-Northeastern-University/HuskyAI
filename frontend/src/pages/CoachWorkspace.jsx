import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { DIM_META } from '../lib/metricInfo'
import { API_URL, authHeaders } from '../lib/api'
import { clearAllReadBuffers, createReadSender } from '../lib/readBuffer'

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

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
function timeAgo(iso) {
  if (!iso) return 'never'
  const s = Math.floor((Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/* ───────────────────────── One artifact section ───────────────────────── */

export function Section({ section, isMine, editorName, onExpand, onCollapse, onSave, conflict, onDismissConflict, justUpdatedBy }) {
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

  // Follow the server's copy while not actively editing, so a teammate's edit
  // lands live instead of being silently overwritten by a stale draft.
  useEffect(() => { if (!editing) setDraft(section.content || '') }, [section.content, section.version, editing])
  // Declared after the effect above so it runs second: on a conflict that effect
  // has just replaced the draft with the teammate's text, and this restores ours.
  useEffect(() => {
    if (!conflict) return
    setSaving(false)
    setDraft(sentDraft.current)
    setBaseVersion(conflict.version)
    setEditing(true)
  }, [conflict])

  const toggle = () => {
    const next = !open
    setOpen(next)
    // The measurement. Fires only from this click.
    next ? onExpand(section.key) : onCollapse(section.key)
  }

  const save = () => {
    setSaving(true)
    sentDraft.current = draft
    onSave(section.key, draft, baseVersion)
    setEditing(false)
  }

  const empty = !(section.content || '').trim()

  return (
    <div className="border border-[#E7E0D8] rounded-[12px] bg-[#FDFCFB] overflow-hidden flex-shrink-0" style={{ borderWidth: '1.5px' }}>
      <button
        onClick={toggle}
        className="w-full px-4 py-3 flex items-center gap-3 hover:bg-[#F7F3EE] cursor-pointer text-left"
      >
        <svg className={`w-3.5 h-3.5 stroke-[#6B6560] fill-none flex-shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
             viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
        <div className="flex-1 min-w-0">
          <div className="text-[13px] font-bold text-[#16120E] truncate">{section.title || section.key}</div>
          <div className="text-[11px] text-[#9A948E] mt-0.5">
            {empty ? 'Empty' : `v${section.version} · ${editorName || 'someone'} · ${timeAgo(section.updated_at)}`}
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
          {conflict && (
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
          )}

          {editing ? (
            <div className="mt-3">
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                rows={8}
                className="w-full p-3 text-[13px] text-[#16120E] bg-white border border-[#E7E0D8] rounded-[10px] resize-y font-mono leading-relaxed focus:outline-none focus:border-[#C8102E]"
                style={{ borderWidth: '1.5px' }}
                placeholder="Write the team's work for this section…"
              />
              <div className="flex gap-2 mt-2">
                <button onClick={save} disabled={saving}
                        className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] hover:bg-[#A50D26] disabled:opacity-50 cursor-pointer">
                  {saving ? 'Saving…' : 'Save'}
                </button>
                <button onClick={() => { setEditing(false); setDraft(section.content || '') }}
                        className="px-3 py-1.5 text-[12px] font-bold text-[#6B6560] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer">
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div className="mt-3">
              {empty
                ? <div className="text-[13px] text-[#9A948E] italic py-2">Nothing here yet.</div>
                : <div className="prose-chat text-[13px] text-[#16120E]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{section.content}</ReactMarkdown></div>}
              <button onClick={() => { setBaseVersion(section.version); setEditing(true) }}
                      className="mt-3 px-3 py-1.5 text-[12px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] hover:bg-[#EDEAE4] cursor-pointer"
                      style={{ borderWidth: '1.5px' }}>
                {empty ? 'Write this section' : 'Edit'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ───────────────────────────── The page ───────────────────────────── */

export default function CoachWorkspace() {
  const navigate = useNavigate()
  const { id: groupId } = useParams()
  const [searchParams] = useSearchParams()
  const sessionNum = searchParams.get('session') || 1

  const token = localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  const myName = user?.name || 'You'

  const [messages, setMessages]       = useState([])
  const [streaming, setStreaming]     = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isTyping, setIsTyping]       = useState(false)
  const [isEvaluating, setIsEval]     = useState(false)
  const [evalData, setEvalData]       = useState(null)
  const [turnCount, setTurnCount]     = useState(0)
  const [input, setInput]             = useState('')
  const [connStatus, setConn]         = useState('disconnected')
  const [members, setMembers]         = useState([])
  const [challengeContext, setCtx]    = useState(null)
  const [condition, setCondition]     = useState(null)

  const [artifact, setArtifact]       = useState(null)
  // Open by default: this is a two-pane workspace, and a collapsed panel reads
  // as "there is no artifact". Only the SECTIONS start collapsed — that is what
  // makes an expand event mean a person chose to read, and it is preserved here.
  // No artifact_open fires on mount: showing the panel is a render, not a read.
  const [artifactOpen, setArtOpen]    = useState(true)
  const [conflicts, setConflicts]     = useState({})
  const [teamChat, setTeamChat]       = useState([])
  const [teamInput, setTeamInput]     = useState('')
  const [sessionEnded, setEnded]      = useState(false)
  const [ending, setEnding]           = useState(false)
  const [summary, setSummary]         = useState(null)
  const [groupSessionId, setGsId]     = useState(null)
  const [inbox, setInbox]             = useState([])
  const [pairs, setPairs]             = useState([])
  const [inboxDirty, setInboxDirty]   = useState(0)
  const [recentEdits, setRecentEdits] = useState({})

  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)
  const streamBuf    = useRef('')
  const endRef       = useRef(null)
  const dwellRef     = useRef({})   // section_key -> started-at ms
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

  const onExpand = useCallback((key) => {
    dwellRef.current[key] = Date.now()
    emit({ type: 'artifact_expand', section_key: key })
  }, [emit])

  const onCollapse = useCallback((key) => {
    const started = dwellRef.current[key]
    delete dwellRef.current[key]
    if (started) {
      const ms = Date.now() - started
      if (ms > 500) emit({ type: 'artifact_dwell', section_key: key, duration_ms: ms })
    }
  }, [emit])

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
      // Closing the panel ends any open dwells.
      for (const key of Object.keys(dwellRef.current)) onCollapse(key)
    }
    setArtOpen(next)
    emit({ type: next ? 'artifact_open' : 'artifact_close' })
  }, [artifactOpen, emit, onCollapse])

  const saveSection = useCallback((key, content, expectedVersion) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    wsRef.current.send(JSON.stringify({
      type: 'artifact_write', section_key: key, content,
      expected_version: expectedVersion, origin: 'student_typed',
    }))
  }, [])

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
        if (data.condition) setCondition(data.condition)
        if (data.group_session_id) setGsId(data.group_session_id)
        break
      case 'challenge_context': setCtx(data.data); break
      case 'history':
        if (Array.isArray(data.messages)) {
          setMessages(data.messages.filter(m => m?.role && typeof m.content === 'string')
            .map(m => ({ role: m.role, content: m.content })))
        }
        if (typeof data.turn_count === 'number') setTurnCount(data.turn_count)
        break
      case 'artifact':
        setArtifact(data.data)
        break
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
        break
      case 'artifact_conflict':
        // Their text wins on screen; our draft stays in the editor to rebase.
        setConflicts(prev => ({ ...prev, [data.section_key]: { version: data.version } }))
        setArtifact(prev => prev && ({
          ...prev,
          sections: prev.sections.map(s => s.key === data.section_key
            ? { ...s, content: data.content, version: data.version } : s),
        }))
        break
      case 'artifact_error':
        console.error('artifact error:', data.message)
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
      case 'eval': setIsEval(false); setEvalData(data.data); setTurnCount(t => t + 1); break
      case 'eval_error': setIsEval(false); break
      case 'presence': if (Array.isArray(data.members)) setMembers(data.members); break
      case 'verification_assigned':
        // A teammate's save was routed to someone; refresh in case it is mine.
        setInboxDirty(n => n + 1)
        break
      case 'team_chat_history':
        if (Array.isArray(data.messages)) {
          setTeamChat(data.messages.map(m => ({
            senderName: m.sender_name, content: m.content, isSelf: m.sender_name === myName,
          })))
        }
        break
      case 'team_chat':
        // Human-only backchannel. Never enters a coach prompt or the evaluator;
        // whether it enters the research record at all is an open question, so
        // nothing here emits a study event.
        setTeamChat(prev => [...prev, { senderName: data.sender_name, content: data.content, isSelf: false }])
        break
      case 'session_ended':
        endedRef.current = true
        setEnded(true)
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
  }, [markRecentEdit, user?.id])

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
      if (e.code === 4001) {
        localStorage.removeItem('token'); localStorage.removeItem('user')
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
  }, [token, groupId, sessionNum, handleMessage, flushOutbox, navigate])

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
    if (!content || isStreaming || isTyping || isEvaluating) return
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ type: 'message', content, attachments: [] }))
    setInput('')
  }, [input, isStreaming, isTyping, isEvaluating])

  const sendTeamChat = useCallback(() => {
    const content = teamInput.trim()
    if (!content || wsRef.current?.readyState !== WebSocket.OPEN) return
    setTeamChat(prev => [...prev, { senderName: myName, content, isSelf: true }])
    wsRef.current.send(JSON.stringify({ type: 'team_chat', content }))
    setTeamInput('')
  }, [teamInput, myName])

  const endSession = useCallback(async () => {
    if (!window.confirm('End this session for the whole team? Everyone will be disconnected.')) return
    setEnding(true)
    try {
      const r = await fetch(`${API_URL}/groups/${groupId}/sessions/${sessionNum}/end`,
        { method: 'POST', headers: authHeaders() })
      if (r.ok) setSummary(await r.json())
      endedRef.current = true
      setEnded(true)
    } catch (e) {
      console.error('could not end session', e)
    } finally {
      setEnding(false)
    }
  }, [groupId, sessionNum])

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
    try {
      const r = await fetch(`${API_URL}/contested/pairs/${pairId}/adopt`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ adopted }),
      })
      if (r.ok) setPairs(prev => prev.filter(x => x.pair_id !== pairId))
    } catch (e) { console.error('adopt failed', e) }
  }, [])

  const nameFor = (uidStr) => {
    if (uidStr && user?.id === uidStr) return 'You'
    return members.find(m => m.user_id === uidStr)?.name
  }

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
            {challengeContext?.title || 'Collaborative session'}
          </div>
          <div className="text-[11px] text-[#9A948E]">
            Session {sessionNum} · Your coach is private to you
            {condition ? ` · ${condition.arm} / ${condition.prominence}` : ''}
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
        {!sessionEnded && (
          <button onClick={endSession} disabled={ending}
                  className="px-3 py-1.5 text-[12px] font-bold text-[#C8102E] bg-[#FDFCFB] border border-[#E7E0D8] rounded-[8px] hover:bg-[#FDE8EC] disabled:opacity-50 cursor-pointer"
                  style={{ borderWidth: '1.5px' }}>
            {ending ? 'Ending…' : 'End session'}
          </button>
        )}
      </div>

      {sessionEnded && (
        <div className="px-6 py-3 bg-[#E6F7F6] border-b border-[#C7E9E6] flex items-center gap-4 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span className="text-[13px] font-bold text-[#0D9488]">Session ended.</span>
          {summary && (
            <span className="text-[12px] text-[#4A4440]">
              Team mean PEI {summary.session_avg_pei ?? '—'} across {summary.turns} turn{summary.turns === 1 ? '' : 's'}
              {summary.per_student && Object.keys(summary.per_student).length > 1 && (
                <> · {Object.entries(summary.per_student)
                  .map(([uidStr, v]) => `${nameFor(uidStr) || 'member'}: ${v.avg_pei ?? '—'} (${v.turns})`)
                  .join(' · ')}</>
              )}
            </span>
          )}
          <button onClick={() => navigate('/challenges')}
                  className="ml-auto text-[12px] font-bold text-[#0D9488] underline cursor-pointer">
            Back to challenges
          </button>
        </div>
      )}

      {connStatus === 'error' && (
        <div className="px-6 py-2 bg-[#FDE8EC] text-[12px] text-[#C8102E] font-bold flex-shrink-0">
          Could not join this session — you may not be a member of this team, or the assignment's artifact is misconfigured.
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* ── Private coach ── */}
        <div className="flex-1 flex flex-col min-w-0 border-r border-[#E7E0D8]" style={{ borderRightWidth: '1.5px' }}>
          <div className="px-5 py-2.5 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center gap-2 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
            <span className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Your private coach</span>
            <span className="text-[10px] text-[#9A948E]">· teammates cannot see this</span>
            {turnCount > 0 && <span className="text-[11px] text-[#9A948E] ml-auto">Turn {turnCount}</span>}
          </div>

          <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
            {challengeContext && messages.length === 0 && (
              <div className="p-4 rounded-[12px] bg-[#FDFCFB] border border-[#E7E0D8]" style={{ borderWidth: '1.5px' }}>
                <div className="text-[13px] font-bold text-[#16120E] mb-1">{challengeContext.title}</div>
                <div className="text-[13px] text-[#4A4440]">{challengeContext.goal}</div>
                {challengeContext.seed_question && (
                  <div className="text-[13px] text-[#6B6560] mt-2 italic">{challengeContext.seed_question}</div>
                )}
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] px-4 py-2.5 rounded-[14px] text-[14px] leading-relaxed ${
                  m.role === 'user'
                    ? 'bg-[#C8102E] text-white'
                    : 'bg-[#FDFCFB] text-[#16120E] border border-[#E7E0D8]'}`}
                     style={m.role === 'user' ? {} : { borderWidth: '1.5px' }}>
                  {m.role === 'user'
                    ? <p className="whitespace-pre-wrap">{m.content}</p>
                    : <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown></div>}
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
            <div ref={endRef} />
          </div>

          <div className="p-4 bg-[#FDFCFB] border-t border-[#E7E0D8] flex-shrink-0" style={{ borderTopWidth: '1.5px' }}>
            <div className="flex gap-2">
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
              <button onClick={send} disabled={busy || !input.trim() || connStatus !== 'connected'}
                      className="px-4 py-2.5 text-[13px] font-bold text-white bg-[#C8102E] rounded-[12px] hover:bg-[#A50D26] disabled:opacity-40 cursor-pointer">
                Send
              </button>
            </div>
          </div>
        </div>

        {/* ── Shared artifact ── */}
        <div className="flex flex-col flex-shrink-0 bg-[#F7F3EE]" style={{ width: artifactOpen ? 460 : 52 }}>
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
                <div>
                  <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Shared Artifact</div>
                  <div className="text-[11px] text-[#9A948E] mt-0.5">Everyone on your team writes here</div>
                </div>
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
                    {[['a', p.option_a], ['b', p.option_b]].map(([k, text]) => (
                      <div key={k} className="mb-2 p-3 rounded-[10px] bg-white border border-[#E7E0D8]"
                           style={{ borderWidth: '1.5px' }}>
                        <div className="text-[13px] text-[#16120E] whitespace-pre-wrap mb-2">{text}</div>
                        <button onClick={() => adoptOption(p.pair_id, k)}
                                className="px-3 py-1 text-[12px] font-bold text-white bg-[#7C3AED] rounded-[8px] cursor-pointer">
                          Use this one
                        </button>
                      </div>
                    ))}
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
                {artifact?.sections?.map(s => (
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
                  />
                ))}
              </div>

              {/* Team backchannel: student-to-student only. Firewalled by design
                  from the coach prompt and the evaluator, and currently emits no
                  study event — whether human deliberation enters the research
                  record is an open question for the PI. Messages are persisted
                  in group_chat_messages either way, so deciding later is free. */}
              <div className="border-t border-[#E7E0D8] flex flex-col flex-shrink-0" style={{ borderTopWidth: '1.5px', height: 240 }}>
                <div className="px-4 py-2 flex items-center gap-2 flex-shrink-0">
                  <span className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Team chat</span>
                  <span className="text-[10px] text-[#9A948E]">· not seen by any coach</span>
                </div>
                <div className="flex-1 overflow-y-auto px-4 pb-2 flex flex-col gap-2">
                  {teamChat.length === 0 && (
                    <div className="text-[12px] text-[#9A948E] italic">Talk to your teammates here.</div>
                  )}
                  {teamChat.map((m, i) => (
                    <div key={i} className={`flex ${m.isSelf ? 'justify-end' : 'justify-start'}`}>
                      <div className={`max-w-[85%] px-3 py-1.5 rounded-[10px] text-[12px] ${
                        m.isSelf ? 'bg-[#EDE9FE] text-[#16120E]' : 'bg-[#F7F3EE] text-[#16120E]'}`}>
                        {!m.isSelf && <div className="text-[10px] font-bold text-[#6B6560] mb-0.5">{m.senderName}</div>}
                        <span className="whitespace-pre-wrap">{m.content}</span>
                      </div>
                    </div>
                  ))}
                  <div ref={teamEndRef} />
                </div>
                <div className="p-3 flex gap-2 flex-shrink-0">
                  <input
                    value={teamInput}
                    onChange={e => setTeamInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); sendTeamChat() } }}
                    placeholder="Message your team…"
                    disabled={sessionEnded || connStatus !== 'connected'}
                    className="flex-1 px-3 py-1.5 text-[12px] bg-white border border-[#E7E0D8] rounded-[8px] focus:outline-none focus:border-[#7C3AED] disabled:opacity-60"
                    style={{ borderWidth: '1.5px' }}
                  />
                  <button onClick={sendTeamChat} disabled={sessionEnded || !teamInput.trim() || connStatus !== 'connected'}
                          className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#7C3AED] rounded-[8px] disabled:opacity-40 cursor-pointer">
                    Send
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
