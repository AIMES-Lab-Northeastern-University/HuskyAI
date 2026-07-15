import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams, Navigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders } from '../lib/api'

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

/* ─── Score helpers (shared visual language with the single-user Workspace) ─── */
function scoreColor(pei) {
  if (pei <= 40) return '#C8102E'
  if (pei <= 65) return '#F97316'
  if (pei <= 80) return '#0D9488'
  return '#16A34A'
}
function scoreBg(pei) {
  if (pei <= 40) return '#FDE8EC'
  if (pei <= 65) return '#FEF3E8'
  if (pei <= 80) return '#E6F7F6'
  return '#DCFCE7'
}
function scoreLabel(pei) {
  if (pei <= 40) return 'Novice'
  if (pei <= 65) return 'Developing'
  if (pei <= 80) return 'Practitioner'
  return 'Expert'
}

const DIM_META = {
  PSQ: { label: 'Prompt Quality',       color: '#C8102E' },
  CCM: { label: 'Conversation Control', color: '#F97316' },
  TSI: { label: 'Tech Sophistication',  color: '#0D9488' },
  CLM: { label: 'Cognitive Load',       color: '#7C3AED' },
  RAS: { label: 'Reliance Calibration', color: '#D97706' },
}

function PeiRing({ pei = 0 }) {
  const r = 50, circ = Math.PI * 2 * r
  const offset = circ - (pei / 100) * circ
  const col = scoreColor(pei)
  return (
    <div className="relative w-[120px] h-[120px] mx-auto mb-3">
      <svg viewBox="0 0 120 120" className="w-[120px] h-[120px] -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#E7E0D8" strokeWidth="9" />
        <circle cx="60" cy="60" r={r} fill="none" stroke={col} strokeWidth="9"
          strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset} className="ring-arc" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-serif text-[28px] text-[#16120E] leading-none">{Math.round(pei)}</span>
        <span className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.5px] mt-0.5">Team Score</span>
      </div>
    </div>
  )
}

function DimBar({ code, value = 0 }) {
  const meta = DIM_META[code] || { label: code, color: '#9A948E' }
  const pct = Math.min(100, value)
  return (
    <div className="mb-[14px]">
      <div className="flex items-center gap-[10px] mb-[4px]">
        <div className="flex items-center gap-[6px] flex-1 min-w-0">
          <span className="text-[11px] font-bold font-mono px-1.5 py-0.5 rounded flex-shrink-0" style={{ color: meta.color, background: `${meta.color}15`, border: `1px solid ${meta.color}30` }}>{code}</span>
          <span className="text-[12px] text-[#4A4440] font-medium truncate">{meta.label}</span>
        </div>
        <div className="text-[12px] font-bold text-[#4A4440] w-8 text-right flex-shrink-0">{Math.round(value)}</div>
      </div>
      <div className="flex-1 h-[6px] bg-[#F7F3EE] rounded-full border border-[#E7E0D8] overflow-hidden">
        <div className="h-full rounded-full prog-fill" style={{ width: `${pct}%`, background: meta.color }} />
      </div>
    </div>
  )
}

function EvalSidebar({ evalData, isEvaluating, turnCount, collapsed, onToggle }) {
  const pei = evalData?.scores?.PEI ?? 0
  const scores = evalData?.scores || {}
  const suggestions = evalData?.suggestions || []
  const classification = evalData?.classification || '-'
  const leadStatus = evalData?.leading_status || '-'

  // Collapsed rail: just an expand button, the Husky Score, and a vertical label.
  if (collapsed) {
    return (
      <div className="h-full bg-[#FDFCFB] border-l border-[#E7E0D8] flex flex-col items-center py-4 gap-3" style={{ borderLeftWidth: '1.5px' }}>
        <button
          onClick={onToggle}
          title="Expand evaluator"
          aria-label="Expand evaluator"
          className="w-8 h-8 rounded-[8px] bg-[#F7F3EE] hover:bg-[#EDEAE4] border border-[#E7E0D8] flex items-center justify-center cursor-pointer"
          style={{ borderWidth: '1.5px' }}
        >
          <svg className="w-4 h-4 stroke-[#6B6560] fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 18l-6-6 6-6"/></svg>
        </button>
        {evalData && (
          <div className="flex flex-col items-center">
            <span className="font-serif text-[20px] leading-none" style={{ color: scoreColor(pei) }}>{Math.round(pei)}</span>
            <span className="text-[8px] font-bold text-[#9A948E] uppercase tracking-[0.5px] mt-1">Score</span>
          </div>
        )}
        {isEvaluating && <div className="w-1.5 h-1.5 rounded-full bg-[#C8102E] live-dot" />}
        <div className="flex-1" />
        <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.7px]" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
          Team Evaluator
        </div>
      </div>
    )
  }

  return (
    <div className="h-full bg-[#FDFCFB] border-l border-[#E7E0D8] flex flex-col overflow-y-auto" style={{ borderLeftWidth: '1.5px' }}>
      <div className="px-5 py-4 border-b border-[#E7E0D8] flex items-center justify-between flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
        <div className="flex items-center gap-2">
          <button
            onClick={onToggle}
            title="Collapse evaluator"
            aria-label="Collapse evaluator"
            className="w-7 h-7 rounded-[8px] bg-[#F7F3EE] hover:bg-[#EDEAE4] border border-[#E7E0D8] flex items-center justify-center cursor-pointer flex-shrink-0"
            style={{ borderWidth: '1.5px' }}
          >
            <svg className="w-3.5 h-3.5 stroke-[#6B6560] fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          </button>
          <div>
            <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Team Evaluator</div>
            {turnCount > 0 && <div className="text-[12px] text-[#9A948E] mt-0.5">Turn {turnCount}</div>}
          </div>
        </div>
        {isEvaluating && (
          <div className="flex items-center gap-1.5 text-[11px] text-[#9A948E]">
            <div className="w-1.5 h-1.5 rounded-full bg-[#C8102E] live-dot" />Scoring…
          </div>
        )}
      </div>
      <div className="p-5 flex flex-col gap-4 flex-1">
        <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5 text-center" style={{ borderWidth: '1.5px' }}>
          <PeiRing pei={pei} />
          <div className="flex items-center justify-center gap-2 mb-1.5">
            <span className="text-[11px] font-bold px-[10px] py-[3px] rounded-[20px]" style={{ background: scoreBg(pei), color: scoreColor(pei) }}>{scoreLabel(pei)}</span>
          </div>
          {classification !== '-' && <div className="text-[12px] text-[#9A948E]">{classification} · {leadStatus}</div>}
        </div>
        <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5" style={{ borderWidth: '1.5px' }}>
          <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-[14px]">Dimension Scores</div>
          {Object.keys(DIM_META).map(k => <DimBar key={k} code={k} value={scores[k] ?? 0} />)}
        </div>
        {suggestions.length > 0 && (
          <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5" style={{ borderWidth: '1.5px' }}>
            <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-3">Coach Suggestions</div>
            {suggestions.map((s, i) => (
              <div key={i} className="bg-[#FEF9EC] border border-[#FDE68A] rounded-[10px] p-3 mb-2 last:mb-0">
                <p className="text-[12px] text-[#92400E] leading-[1.6]">{s}</p>
              </div>
            ))}
          </div>
        )}
        {!evalData && !isEvaluating && (
          <div className="flex-1 flex flex-col items-center justify-center text-center py-10">
            <div className="text-[13px] font-medium text-[#4A4440] mb-1">No evaluation yet</div>
            <div className="text-[12px] text-[#9A948E]">Send a message to get the team scored</div>
          </div>
        )}
      </div>
    </div>
  )
}

/* Stable per-person colour from a name, so each teammate reads consistently. */
const AVATAR_COLORS = ['#C8102E', '#0D9488', '#7C3AED', '#D97706', '#2563EB', '#DB2777']
function colorFor(name) {
  let h = 0
  for (const ch of (name || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return AVATAR_COLORS[h % AVATAR_COLORS.length]
}
function initials(name) {
  return (name || '?').split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase()
}

/* ─── Group message bubble: user prompts are attributed to their author. ─── */
function GroupMessage({ role, content, attachments, senderName, isSelf }) {
  const isUser = role === 'user'
  const col = colorFor(senderName)
  return (
    <div className={`flex gap-3 message-enter ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-[#C8102E] flex items-center justify-center flex-shrink-0 mt-0.5">
          <svg className="w-3.5 h-3.5 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
            <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
          </svg>
        </div>
      )}
      <div className="flex flex-col" style={{ maxWidth: '75%', alignItems: isUser ? 'flex-end' : 'flex-start' }}>
        {isUser && senderName && (
          <div className="text-[11px] text-[#9A948E] mb-1 px-1">{isSelf ? 'You' : senderName}</div>
        )}
        <div className={`px-4 py-3 rounded-[14px] text-[14px] leading-[1.65] border ${
          isUser ? 'bg-[#EDEAE4] border-[#E7E0D8] text-[#16120E] rounded-br-[4px]'
                 : 'bg-[#FDFCFB] border-[#E7E0D8] text-[#16120E] rounded-bl-[4px]'
        }`} style={{ borderWidth: '1.5px' }}>
          {Array.isArray(attachments) && attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2">
              {attachments.map((a, i) => (
                <span key={i} className="inline-flex items-center gap-1 px-2 py-1 rounded-[8px] border border-[#D8D0C6] bg-[#FDFCFB] text-[11px] text-[#4A4440]">{a.name}</span>
              ))}
            </div>
          )}
          {isUser
            ? (content ? <p>{content}</p> : null)
            : <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>}
        </div>
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 text-[11px] font-bold text-white" style={{ background: col }}>
          {initials(senderName)}
        </div>
      )}
    </div>
  )
}

export default function GroupChat() {
  const navigate = useNavigate()
  const { id: groupId } = useParams()
  const [searchParams] = useSearchParams()
  const sessionNum = searchParams.get('session') || 1

  const token = localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')
  const myName = user?.name || 'You'

  const [messages, setMessages]          = useState([])
  const [streamingContent, setStreaming] = useState('')
  const [isStreaming, setIsStreaming]    = useState(false)
  const [isTyping, setIsTyping]          = useState(false)
  const [isEvaluating, setIsEvaluating]  = useState(false)
  const [evalData, setEvalData]          = useState(null)
  const [turnCount, setTurnCount]        = useState(0)
  const [evalCollapsed, setEvalCollapsed] = useState(false)
  // Width of the left "Team chat" column; the coach column flexes to fill the rest.
  const [teamWidth, setTeamWidth]        = useState(300)

  const chatRowRef = useRef(null)

  // Drag the divider between Team chat and the coach chat to resize the split.
  // The coach (LLM) chat keeps a readable minimum width: we cap how wide Team chat
  // can grow based on the row width minus the eval panel and that minimum.
  const startTeamResize = useCallback((e) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = teamWidth
    const MIN_TEAM = 220
    const MIN_COACH = 360
    const DIVIDER = 6
    const onMove = (ev) => {
      const rowW = chatRowRef.current?.getBoundingClientRect().width ?? window.innerWidth
      const evalW = evalCollapsed ? 52 : 380
      const maxTeam = Math.max(MIN_TEAM, rowW - evalW - DIVIDER - MIN_COACH)
      const next = startW + (ev.clientX - startX)
      setTeamWidth(Math.min(Math.max(next, MIN_TEAM), maxTeam))
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [teamWidth, evalCollapsed])
  const [connStatus, setConnStatus]      = useState('disconnected')
  const [input, setInput]                = useState('')
  const [members, setMembers]            = useState([])
  const [busyNotice, setBusyNotice]      = useState(false)
  const [challengeContext, setChallengeContext] = useState(null)
  const [sessionEnded, setSessionEnded]  = useState(false)
  const [ending, setEnding]              = useState(false)
  const [sessionScore, setSessionScore]  = useState(null)
  const [teamChat, setTeamChat]          = useState([])
  const [teamInput, setTeamInput]        = useState('')
  const [waitingNotice, setWaitingNotice] = useState('')
  const [peerTyping, setPeerTyping]      = useState({ coach: null, team: null })

  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const sessionEndedRef = useRef(false)
  const streamBuffer = useRef('')
  const messagesEndRef = useRef(null)
  const teamEndRef = useRef(null)
  const textareaRef = useRef(null)
  const busyTimer = useRef(null)
  const waitingTimer = useRef(null)
  const typingSentRef = useRef({ coach: 0, team: 0 })
  const peerTypingClear = useRef({})

  // Throttled "I'm typing" ping (once per ~1.5s per pane) so teammates see a cue.
  const pingTyping = useCallback((scope) => {
    const now = Date.now()
    if (now - (typingSentRef.current[scope] || 0) < 1500) return
    typingSentRef.current[scope] = now
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'typing_indicator', scope }))
    }
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('token'); localStorage.removeItem('user')
    wsRef.current?.close(); navigate('/login', { replace: true })
  }

  const handleWsMessage = useCallback((data) => {
    switch (data.type) {
      case 'session_init':
        if (typeof data.turn_count === 'number') setTurnCount(data.turn_count)
        break
      case 'challenge_context': setChallengeContext(data.data); break
      case 'history':
        if (Array.isArray(data.messages)) {
          setMessages(data.messages
            .filter(m => m && typeof m.role === 'string' && typeof m.content === 'string')
            .map(m => ({
              role: m.role, content: m.content,
              senderName: m.sender_name,
              isSelf: m.sender_name === myName,
              attachments: Array.isArray(m.attachments) && m.attachments.length ? m.attachments : undefined,
            })))
        }
        if (typeof data.turn_count === 'number') setTurnCount(data.turn_count)
        break
      case 'user_message':
        // A teammate's prompt (the server excludes our own; we render those optimistically).
        setMessages(prev => [...prev, {
          role: 'user', content: data.content,
          senderName: data.sender_name, isSelf: false,
          attachments: Array.isArray(data.attachments) && data.attachments.length ? data.attachments : undefined,
        }])
        setPeerTyping(prev => ({ ...prev, coach: null }))
        break
      case 'typing':
        setIsTyping(true); setIsStreaming(false); streamBuffer.current = ''; setStreaming('')
        break
      case 'stream':
        setIsTyping(false); setIsStreaming(true)
        streamBuffer.current += data.content
        setStreaming(prev => prev + data.content)
        break
      case 'done':
        setIsStreaming(false); setIsTyping(false)
        setMessages(prev => [...prev, { role: 'assistant', content: data.full_response || streamBuffer.current }])
        streamBuffer.current = ''; setStreaming('')
        break
      case 'eval_start': setIsEvaluating(true); break
      case 'eval':
        setIsEvaluating(false); setEvalData(data.data); setTurnCount(t => t + 1)
        break
      case 'eval_error': setIsEvaluating(false); break
      case 'busy':
        // Another teammate's turn is in flight; flash a brief notice.
        setBusyNotice(true)
        clearTimeout(busyTimer.current)
        busyTimer.current = setTimeout(() => setBusyNotice(false), 2500)
        break
      case 'waiting':
        // Strict group-only: not enough teammates online to message the coach.
        setWaitingNotice(`Waiting for teammates — at least ${data.needed} must be online to message the coach (${data.present} here now).`)
        clearTimeout(waitingTimer.current)
        waitingTimer.current = setTimeout(() => setWaitingNotice(''), 4500)
        break
      case 'team_chat_history':
        if (Array.isArray(data.messages)) {
          setTeamChat(data.messages.map(m => ({
            senderName: m.sender_name, content: m.content,
            isSelf: m.sender_name === myName,
          })))
        }
        break
      case 'team_chat':
        // A teammate's backchannel message (server excludes our own; we render those optimistically).
        setTeamChat(prev => [...prev, { senderName: data.sender_name, content: data.content, isSelf: false }])
        // Their message arrived, so they're no longer "typing" in the team pane.
        setPeerTyping(prev => ({ ...prev, team: null }))
        break
      case 'peer_typing': {
        const scope = data.scope === 'coach' ? 'coach' : 'team'
        setPeerTyping(prev => ({ ...prev, [scope]: data.name }))
        clearTimeout(peerTypingClear.current[scope])
        peerTypingClear.current[scope] = setTimeout(() => setPeerTyping(prev => ({ ...prev, [scope]: null })), 3000)
        break
      }
      case 'member_joined':
      case 'member_left':
        break // presence carries the authoritative roster
      case 'presence':
        if (Array.isArray(data.members)) setMembers(data.members)
        break
      case 'session_ended':
        sessionEndedRef.current = true; setSessionEnded(true)
        break
      case 'error':
        setIsStreaming(false); setIsTyping(false); setIsEvaluating(false)
        console.error('Server error:', data.message); break
      default: break
    }
  }, [myName])

  const connect = useCallback(() => {
    if (!token || !groupId) return
    // Tear down any existing socket WITHOUT letting its onclose schedule a
    // reconnect — otherwise React 18 StrictMode (mount→unmount→remount) and
    // reconnect-on-intentional-close leave a second live socket, which makes the
    // server's broadcasts (that only exclude the *sending* socket) render twice.
    if (wsRef.current) {
      try { wsRef.current.onclose = null; wsRef.current.close() } catch {}
      wsRef.current = null
    }
    setConnStatus('connecting')
    const wsUrl = `${WS_BASE}/group?token=${token}&group_id=${groupId}&session_num=${sessionNum}`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws
    ws.onopen = () => { setConnStatus('connected'); clearTimeout(reconnectTimer.current) }
    ws.onclose = (e) => {
      if (wsRef.current !== ws) return // superseded by a newer socket; ignore
      setConnStatus('disconnected'); setIsStreaming(false); setIsTyping(false); setIsEvaluating(false)
      if (e.code === 4001) { handleLogout(); return }
      if (e.code === 4003) { setConnStatus('error'); return } // not a member — don't retry
      if (sessionEndedRef.current) return
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => setConnStatus('error')
    ws.onmessage = (e) => { try { handleWsMessage(JSON.parse(e.data)) } catch {} }
  }, [token, groupId, sessionNum, handleWsMessage]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!token) { navigate('/login', { replace: true }); return }
    connect()
    return () => {
      clearTimeout(reconnectTimer.current); clearTimeout(busyTimer.current); clearTimeout(waitingTimer.current)
      Object.values(peerTypingClear.current).forEach(clearTimeout)
      // Null onclose so the intentional teardown doesn't trigger a reconnect.
      if (wsRef.current) { try { wsRef.current.onclose = null; wsRef.current.close() } catch {} ; wsRef.current = null }
    }
  }, [connect, token, navigate])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, streamingContent])
  useEffect(() => { teamEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [teamChat])

  const sendTeamChat = useCallback(() => {
    const content = teamInput.trim()
    if (!content) return
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    // Optimistically render our own message (the server won't echo it back).
    setTeamChat(prev => [...prev, { senderName: myName, content, isSelf: true }])
    wsRef.current.send(JSON.stringify({ type: 'team_chat', content }))
    setTeamInput('')
  }, [teamInput, myName])

  const handleTeamKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTeamChat() } }

  const handleSend = useCallback(() => {
    const content = input.trim()
    if (!content || isStreaming || isTyping || isEvaluating || sessionEnded) return
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    // Optimistically render our own prompt (server won't echo it back to us).
    setMessages(prev => [...prev, { role: 'user', content, senderName: myName, isSelf: true }])
    wsRef.current.send(JSON.stringify({ type: 'message', content, attachments: [] }))
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [input, isStreaming, isTyping, isEvaluating, sessionEnded, myName])

  const handleKeyDown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }
  const handleTextarea = (e) => {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
    if (e.target.value.trim()) pingTyping('coach')
  }

  const endSession = async () => {
    if (ending) return
    setEnding(true)
    try {
      const res = await fetch(`${API_URL}/groups/${groupId}/sessions/${sessionNum}/end`, {
        method: 'POST', headers: { ...authHeaders() },
      })
      const data = await res.json()
      if (res.ok) {
        setSessionScore(data.session_avg_pei)
        sessionEndedRef.current = true
        setSessionEnded(true)
      }
    } finally {
      setEnding(false)
    }
  }

  if (!token) return <Navigate to="/login" replace />

  const busy = isStreaming || isTyping || isEvaluating
  const connDot = { connected: '#16A34A', connecting: '#F97316', error: '#C8102E', disconnected: '#9A948E' }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar with presence */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <button onClick={() => navigate('/challenges')} style={{ display: 'flex', alignItems: 'center', gap: '5px', background: 'none', border: 'none', cursor: 'pointer', color: '#9A948E', fontSize: '12px', padding: 0 }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
            Challenges
          </button>
          <span style={{ color: '#E7E0D8' }}>/</span>
          <span className="text-[14px] font-semibold text-[#16120E]">{challengeContext?.title || 'Group session'}</span>
          <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '20px', background: '#EDE9FE', color: '#7C3AED' }}>Group</span>

          {/* Presence avatars */}
          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center -space-x-2 mr-2">
              {members.map((m) => (
                <div key={m.user_id} title={m.name}
                  className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white border-2 border-[#FDFCFB]"
                  style={{ background: colorFor(m.name) }}>
                  {initials(m.name)}
                </div>
              ))}
            </div>
            <span className="text-[12px] text-[#9A948E]">{members.length} online</span>
            <div className="w-1.5 h-1.5 rounded-full ml-2" style={{ background: connDot[connStatus] }} title={connStatus} />
          </div>
        </div>

        <div ref={chatRowRef} className="flex-1 flex overflow-hidden">
          {/* Team backchannel — private to the team; never seen by the coach/LLM */}
          <div className="flex-shrink-0 flex flex-col bg-[#FBF9F6] border-r border-[#E7E0D8] overflow-hidden" style={{ width: `${teamWidth}px`, borderRightWidth: '1.5px' }}>
            <div className="px-4 py-3 border-b border-[#E7E0D8] flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
              <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Team chat</div>
              <div className="text-[11px] text-[#9A948E] mt-0.5">Private to your team — the coach can't see this</div>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-2.5">
              {teamChat.length === 0 && (
                <div className="text-[12px] text-[#9A948E] text-center mt-4 px-2 leading-[1.6]">
                  Discuss strategy here, then send your best prompt to the coach on the right.
                </div>
              )}
              {teamChat.map((m, i) => (
                <div key={i} className={`flex flex-col ${m.isSelf ? 'items-end' : 'items-start'}`}>
                  <div className="text-[10px] text-[#9A948E] mb-0.5 px-1">{m.isSelf ? 'You' : m.senderName}</div>
                  <div className="px-3 py-2 rounded-[10px] text-[13px] leading-[1.5]" style={{ maxWidth: '90%', background: m.isSelf ? '#EDE9FE' : '#fff', border: '1px solid #E7E0D8', color: '#16120E' }}>
                    {m.content}
                  </div>
                </div>
              ))}
              <div ref={teamEndRef} />
            </div>
            <div className="flex-shrink-0 px-3 py-3 border-t border-[#E7E0D8]" style={{ borderTopWidth: '1.5px' }}>
              {peerTyping.team && (
                <div className="text-[11px] text-[#9A948E] italic mb-1.5 px-1">
                  {peerTyping.team} is typing<span className="typing-dots">…</span>
                </div>
              )}
              <div className="bg-[#fff] border border-[#E7E0D8] rounded-[10px] px-3 py-2 flex gap-2 items-end" style={{ borderWidth: '1.5px' }}>
                <textarea
                  value={teamInput}
                  onChange={(e) => { setTeamInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px'; if (e.target.value.trim()) pingTyping('team') }}
                  onKeyDown={handleTeamKeyDown}
                  placeholder="Message your team…"
                  rows={1}
                  className="flex-1 resize-none outline-none bg-transparent text-[13px] text-[#16120E] placeholder-[#9A948E] leading-[1.5] max-h-[120px]"
                  style={{ fontFamily: "'DM Sans', sans-serif" }}
                />
                <button
                  onClick={sendTeamChat}
                  disabled={!teamInput.trim() || connStatus !== 'connected'}
                  className="w-8 h-8 rounded-[8px] bg-[#7C3AED] hover:bg-[#6D28D9] disabled:opacity-40 flex items-center justify-center flex-shrink-0 border-none cursor-pointer"
                  aria-label="Send to team"
                >
                  <svg className="w-3.5 h-3.5 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                </button>
              </div>
            </div>
          </div>

          {/* Drag handle to resize the Team chat / coach chat split */}
          <div
            onMouseDown={startTeamResize}
            title="Drag to resize"
            className="w-1.5 flex-shrink-0 cursor-col-resize bg-transparent hover:bg-[#D8D0C6] active:bg-[#C8102E] transition-colors"
          />

          {/* Coach chat column */}
          <div className="flex-1 flex flex-col overflow-hidden min-w-0">
            {challengeContext && (
              <div className="px-6 pt-4">
                <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[12px] p-4" style={{ borderWidth: '1.5px' }}>
                  <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-1">Goal</div>
                  <div className="text-[13px] text-[#4A4440] leading-[1.6]">{challengeContext.goal || challengeContext.brief}</div>
                </div>
              </div>
            )}

            <div className="flex-1 overflow-y-auto px-6 py-6 flex flex-col gap-5">
              {messages.length === 0 && !isStreaming && (
                <div className="flex-1 flex flex-col items-center justify-center text-center text-[#9A948E]">
                  <div className="text-[14px] font-medium text-[#4A4440] mb-1">Your team's shared chat</div>
                  <div className="text-[12px]">Anyone can send a prompt — you'll all see the coach's reply and one shared score.</div>
                </div>
              )}
              {messages.map((m, i) => (
                <GroupMessage key={i} role={m.role} content={m.content} attachments={m.attachments} senderName={m.senderName} isSelf={m.isSelf} />
              ))}
              {isTyping && (
                <div className="flex gap-3 justify-start">
                  <div className="w-7 h-7 rounded-full bg-[#C8102E] flex-shrink-0" />
                  <div className="px-4 py-3 rounded-[14px] bg-[#FDFCFB] border border-[#E7E0D8] text-[#9A948E] text-[13px]" style={{ borderWidth: '1.5px' }}>Coach is thinking…</div>
                </div>
              )}
              {isStreaming && streamingContent && (
                <GroupMessage role="assistant" content={streamingContent} />
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Composer */}
            <div className="flex-shrink-0 px-6 py-4 border-t border-[#E7E0D8] bg-[#FDFCFB]" style={{ borderTopWidth: '1.5px' }}>
              {busyNotice && !sessionEnded && (
                <div className="text-[12px] text-[#C2410C] bg-[#FEF3E8] border border-[#FED7AA] rounded-[8px] px-3 py-2 mb-2 text-center">
                  A teammate is sending a message — hold on a moment.
                </div>
              )}
              {waitingNotice && !sessionEnded && (
                <div className="text-[12px] text-[#C2410C] bg-[#FEF3E8] border border-[#FED7AA] rounded-[8px] px-3 py-2 mb-2 text-center">
                  {waitingNotice}
                </div>
              )}
              {peerTyping.coach && !sessionEnded && (
                <div className="text-[11px] text-[#9A948E] italic mb-2 px-1">
                  {peerTyping.coach} is typing<span className="typing-dots">…</span>
                </div>
              )}
              {sessionEnded ? (
                <div className="bg-[#F7F3EE] border border-[#E7E0D8] rounded-[12px] px-4 py-3.5 text-center text-[13px] text-[#9A948E]" style={{ borderWidth: '1.5px' }}>
                  Session ended
                  {sessionScore != null && <span> · Team avg PEI: <strong style={{ color: '#C8102E' }}>{sessionScore}</strong></span>}
                </div>
              ) : (
                <>
                  <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] px-4 py-3 flex gap-3 items-end" style={{ borderWidth: '1.5px' }}>
                    <textarea
                      ref={textareaRef}
                      value={input}
                      onChange={handleTextarea}
                      onKeyDown={handleKeyDown}
                      placeholder="Write a prompt for the team… (Shift+Enter for new line)"
                      rows={1}
                      className="flex-1 resize-none outline-none bg-transparent text-[14px] text-[#16120E] placeholder-[#9A948E] leading-[1.6] max-h-[160px]"
                      style={{ fontFamily: "'DM Sans', sans-serif" }}
                    />
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || busy || connStatus !== 'connected'}
                      className="w-9 h-9 rounded-[9px] bg-[#C8102E] hover:bg-[#9E0B24] disabled:opacity-40 flex items-center justify-center flex-shrink-0 border-none cursor-pointer"
                    >
                      <svg className="w-4 h-4 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    </button>
                  </div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-[11px] text-[#9A948E]">Powered by Gemini 2.5 Pro · One shared Husky Score</span>
                    <button onClick={endSession} disabled={ending} className="text-[12px] text-[#C8102E] font-semibold bg-transparent border-none cursor-pointer disabled:opacity-50">
                      {ending ? 'Ending…' : 'End session'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Shared eval panel */}
          <div className={`${evalCollapsed ? 'w-[52px]' : 'w-[380px]'} flex-shrink-0 overflow-hidden transition-[width] duration-200`}>
            <EvalSidebar
              evalData={evalData}
              isEvaluating={isEvaluating}
              turnCount={turnCount}
              collapsed={evalCollapsed}
              onToggle={() => setEvalCollapsed(c => !c)}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
