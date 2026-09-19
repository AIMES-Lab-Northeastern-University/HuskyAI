import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { DIM_META } from '../lib/metricInfo'

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

const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

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

function Section({ section, isMine, editorName, onExpand, onCollapse, onSave, conflict, onDismissConflict, justUpdatedBy }) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(section.content || '')
  const [saving, setSaving] = useState(false)

  // Follow the server's copy while not actively editing, so a teammate's edit
  // lands live instead of being silently overwritten by a stale draft.
  useEffect(() => { if (!editing) setDraft(section.content || '') }, [section.content, section.version, editing])
  useEffect(() => { if (conflict) setSaving(false) }, [conflict])

  const toggle = () => {
    const next = !open
    setOpen(next)
    // The measurement. Fires only from this click.
    next ? onExpand(section.key) : onCollapse(section.key)
  }

  const save = () => {
    setSaving(true)
    onSave(section.key, draft, section.version)
    setEditing(false)
  }

  const empty = !(section.content || '').trim()

  return (
    <div className="border border-[#E7E0D8] rounded-[12px] bg-[#FDFCFB] overflow-hidden" style={{ borderWidth: '1.5px' }}>
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
                Their version (v{conflict.version}) is now shown below. Your draft was not lost — it is in the editor.
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
              <button onClick={() => setEditing(true)}
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
  const [recentEdits, setRecentEdits] = useState({})

  const wsRef        = useRef(null)
  const reconnectRef = useRef(null)
  const streamBuf    = useRef('')
  const endRef       = useRef(null)
  const dwellRef     = useRef({})   // section_key -> started-at ms
  const outbox       = useRef([])   // read events buffered while disconnected
  const recentTimers = useRef({})

  /* Read events. Buffered across a dropped socket and flushed on reconnect with
   * their ORIGINAL client_ts, because a flaky network must not silently eat
   * reads. Each carries an idempotency key so an at-least-once flush counts once. */
  const emit = useCallback((payload) => {
    const msg = { ...payload, event_id: uid(), client_ts: new Date().toISOString() }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    } else {
      outbox.current.push(msg)
    }
  }, [])

  const flushOutbox = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    const queued = outbox.current
    outbox.current = []
    for (const m of queued) wsRef.current.send(JSON.stringify(m))
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

  const togglePanel = useCallback(() => {
    setArtOpen(prev => {
      const next = !prev
      emit({ type: next ? 'artifact_open' : 'artifact_close' })
      if (!next) {
        // Closing the panel ends any open dwells.
        for (const key of Object.keys(dwellRef.current)) onCollapse(key)
      }
      return next
    })
  }, [emit, onCollapse])

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
        navigate('/login', { replace: true }); return
      }
      if (e.code === 4003 || e.code === 4005) { setConn('error'); return }
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

  const send = useCallback(() => {
    const content = input.trim()
    if (!content || isStreaming || isTyping || isEvaluating) return
    if (wsRef.current?.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ type: 'message', content, attachments: [] }))
    setInput('')
  }, [input, isStreaming, isTyping, isEvaluating])

  const nameFor = (uidStr) => {
    if (uidStr && user?.id === uidStr) return 'You'
    return members.find(m => m.user_id === uidStr)?.name
  }

  const pei = evalData?.scores?.PEI ?? 0
  const busy = isStreaming || isTyping || isEvaluating

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
      </div>

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

              <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3">
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
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
