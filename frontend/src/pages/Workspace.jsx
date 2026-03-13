import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, Navigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Sidebar from '../components/Sidebar'

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

/* ─── Score helpers ─── */
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

/* ─── PEI Ring ─── */
function PeiRing({ pei = 0 }) {
  const r = 50, circ = Math.PI * 2 * r
  const offset = circ - (pei / 100) * circ
  const col = scoreColor(pei)
  return (
    <div className="relative w-[120px] h-[120px] mx-auto mb-3">
      <svg viewBox="0 0 120 120" className="w-[120px] h-[120px] -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="#E7E0D8" strokeWidth="9" />
        <circle cx="60" cy="60" r={r} fill="none" stroke={col} strokeWidth="9"
          strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={offset}
          className="ring-arc" />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-serif text-[28px] text-[#16120E] leading-none">{Math.round(pei)}</span>
        <span className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.5px] mt-0.5">Husky Score</span>
      </div>
    </div>
  )
}

/* ─── Dimension bar ─── */
function DimBar({ code, value = 0, max = 100 }) {
  const meta = DIM_META[code] || { label: code, color: '#9A948E' }
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div className="flex items-center gap-[10px] mb-[10px]">
      <div className="text-[12px] text-[#4A4440] font-medium w-[90px] flex-shrink-0">{code}</div>
      <div className="flex-1 h-[7px] bg-[#F7F3EE] rounded-full border border-[#E7E0D8] overflow-hidden">
        <div className="h-full rounded-full prog-fill" style={{ width: `${pct}%`, background: meta.color }} />
      </div>
      <div className="text-[12px] font-bold text-[#4A4440] w-8 text-right">{Math.round(value)}</div>
    </div>
  )
}

/* ─── Eval Panel ─── */
function EvalSidebar({ evalData, isEvaluating, turnCount }) {
  const pei = evalData?.scores?.PEI ?? 0
  const scores = evalData?.scores || {}
  const suggestions = evalData?.suggestions || []
  const classification = evalData?.classification || '—'
  const leadStatus = evalData?.leading_status || '—'

  return (
    <div className="h-full bg-[#FDFCFB] border-l border-[#E7E0D8] flex flex-col overflow-y-auto" style={{ borderLeftWidth: '1.5px' }}>
      {/* Header */}
      <div className="px-5 py-4 border-b border-[#E7E0D8] flex items-center justify-between flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
        <div>
          <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">Prompt Evaluator</div>
          {turnCount > 0 && <div className="text-[12px] text-[#9A948E] mt-0.5">Turn {turnCount}</div>}
        </div>
        {isEvaluating && (
          <div className="flex items-center gap-1.5 text-[11px] text-[#9A948E]">
            <div className="w-1.5 h-1.5 rounded-full bg-[#C8102E] live-dot" />
            Scoring…
          </div>
        )}
      </div>

      <div className="p-5 flex flex-col gap-4 flex-1">
        {/* PEI ring */}
        <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5 text-center" style={{ borderWidth: '1.5px' }}>
          <PeiRing pei={pei} />
          <div className="flex items-center justify-center gap-2 mb-1.5">
            <span className="text-[11px] font-bold px-[10px] py-[3px] rounded-[20px]"
              style={{ background: scoreBg(pei), color: scoreColor(pei) }}>
              {scoreLabel(pei)}
            </span>
          </div>
          {classification !== '—' && (
            <div className="text-[12px] text-[#9A948E]">{classification} · {leadStatus}</div>
          )}
        </div>

        {/* Dimension breakdown */}
        <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5" style={{ borderWidth: '1.5px' }}>
          <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-[14px]">Dimension Scores</div>
          {Object.keys(DIM_META).map(k => (
            <DimBar key={k} code={k} value={scores[k] ?? 0} max={100} />
          ))}
        </div>

        {/* Suggestions */}
        {suggestions.length > 0 && (
          <div className="bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] p-5" style={{ borderWidth: '1.5px' }}>
            <div className="text-[11px] font-bold text-[#9A948E] uppercase tracking-[0.7px] mb-3">Coach Suggestions</div>
            {suggestions.map((s, i) => (
              <div key={i} className="flex items-start gap-[8px] bg-[#FEF9EC] border border-[#FDE68A] rounded-[10px] p-3 mb-2 last:mb-0">
                <svg className="w-[14px] h-[14px] flex-shrink-0 mt-[1px]" viewBox="0 0 24 24" fill="none" stroke="#D97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
                </svg>
                <p className="text-[12px] text-[#92400E] leading-[1.6]">{s}</p>
              </div>
            ))}
          </div>
        )}

        {/* Empty state */}
        {!evalData && !isEvaluating && (
          <div className="flex-1 flex flex-col items-center justify-center text-center py-10">
            <div className="w-10 h-10 rounded-full bg-[#F7F3EE] flex items-center justify-center mb-3">
              <svg className="w-5 h-5 text-[#9A948E]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>
              </svg>
            </div>
            <div className="text-[13px] font-medium text-[#4A4440] mb-1">No evaluation yet</div>
            <div className="text-[12px] text-[#9A948E]">Send a message to get scored</div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── Message bubble ─── */
function Message({ role, content }) {
  const isUser = role === 'user'
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
      <div className={`max-w-[75%] px-4 py-3 rounded-[14px] text-[14px] leading-[1.65] border ${
        isUser
          ? 'bg-[#EDEAE4] border-[#E7E0D8] text-[#16120E] rounded-br-[4px]'
          : 'bg-[#FDFCFB] border-[#E7E0D8] text-[#16120E] rounded-bl-[4px]'
      }`} style={{ borderWidth: '1.5px' }}>
        {isUser
          ? <p>{content}</p>
          : <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown></div>
        }
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-[#E7E0D8] flex items-center justify-center flex-shrink-0 mt-0.5 text-[11px] font-bold text-[#4A4440]">
          Y
        </div>
      )}
    </div>
  )
}

/* ─── Main Workspace ─── */
export default function Workspace() {
  const navigate = useNavigate()
  const token = localStorage.getItem('token')
  const user = JSON.parse(localStorage.getItem('user') || 'null')

  const [messages, setMessages]           = useState([])
  const [streamingContent, setStreaming]  = useState('')
  const [isStreaming, setIsStreaming]     = useState(false)
  const [isTyping, setIsTyping]           = useState(false)
  const [isEvaluating, setIsEvaluating]  = useState(false)
  const [evalData, setEvalData]           = useState(null)
  const [connStatus, setConnStatus]       = useState('disconnected')
  const [turnCount, setTurnCount]         = useState(0)
  const [input, setInput]                 = useState('')

  const wsRef              = useRef(null)
  const reconnectTimer     = useRef(null)
  const streamBuffer       = useRef('')
  const messagesEndRef     = useRef(null)
  const textareaRef        = useRef(null)

  const userInitials = user?.name ? user.name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() : 'U'

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    wsRef.current?.close()
    navigate('/login', { replace: true })
  }

  const handleWsMessage = useCallback((data) => {
    switch (data.type) {
      case 'typing':
        setIsTyping(true); setIsStreaming(false)
        streamBuffer.current = ''; setStreaming('')
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
      case 'eval':       setIsEvaluating(false); setEvalData(data.data); setTurnCount(t => t + 1); break
      case 'eval_error': setIsEvaluating(false); break
      case 'error':
        setIsStreaming(false); setIsTyping(false); setIsEvaluating(false)
        console.error('Server error:', data.message); break
      default: break
    }
  }, [])

  const connect = useCallback(() => {
    if (!token) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    setConnStatus('connecting')
    const ws = new WebSocket(`${WS_BASE}?token=${token}`)
    wsRef.current = ws
    ws.onopen  = () => { setConnStatus('connected'); clearTimeout(reconnectTimer.current) }
    ws.onclose = (e) => {
      setConnStatus('disconnected'); setIsStreaming(false); setIsTyping(false); setIsEvaluating(false)
      if (e.code === 4001) { handleLogout(); return }
      reconnectTimer.current = setTimeout(connect, 3000)
    }
    ws.onerror = () => setConnStatus('error')
    ws.onmessage = (e) => { try { handleWsMessage(JSON.parse(e.data)) } catch {} }
  }, [token, handleWsMessage])

  useEffect(() => {
    if (!token) { navigate('/login', { replace: true }); return }
    connect()
    return () => { clearTimeout(reconnectTimer.current); wsRef.current?.close() }
  }, [connect])

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, streamingContent])

  const handleSend = useCallback(() => {
    const content = input.trim()
    if (!content || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (isStreaming || isTyping) return
    setMessages(prev => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ type: 'message', content }))
    setInput('')
    if (textareaRef.current) { textareaRef.current.style.height = 'auto' }
  }, [input, isStreaming, isTyping])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const handleTextarea = (e) => {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
  }

  if (!token) return <Navigate to="/login" replace />

  const connDot = { connected: '#16A34A', connecting: '#F97316', error: '#C8102E', disconnected: '#9A948E' }

  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={handleLogout} />

      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: '220px' }}>

        {/* Topbar */}
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 gap-3 flex-shrink-0 sticky top-0 z-10" style={{ borderBottomWidth: '1.5px' }}>
          <div>
            <span className="text-[15px] font-semibold text-[#16120E]">Workspace</span>
            <span className="text-[12px] text-[#9A948E] ml-2">AI Coding Assistant</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-[12px] text-[#9A948E]">
              <div className="w-[6px] h-[6px] rounded-full" style={{ background: connDot[connStatus] }} />
              {connStatus === 'connected' ? 'Connected' : connStatus === 'connecting' ? 'Connecting…' : 'Disconnected'}
            </div>
          </div>
        </div>

        {/* Two-panel layout */}
        <div className="flex-1 flex overflow-hidden">

          {/* Chat panel */}
          <div className="flex flex-col flex-1 overflow-hidden bg-[#F7F3EE]">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
              {messages.length === 0 && !isTyping && !isStreaming && (
                <div className="flex-1 flex flex-col items-center justify-center text-center py-20">
                  <div className="w-12 h-12 bg-[#C8102E] rounded-[14px] flex items-center justify-center mb-4 mx-auto">
                    <svg className="w-6 h-6 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
                      <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
                    </svg>
                  </div>
                  <h2 className="font-serif text-[22px] text-[#16120E] mb-2">Start your session</h2>
                  <p className="text-[13px] text-[#9A948E] max-w-[320px] leading-[1.65]">Ask a coding question. Your prompting style will be scored in real time.</p>
                </div>
              )}

              {messages.map((m, i) => <Message key={i} role={m.role} content={m.content} />)}

              {/* Typing / streaming */}
              {isTyping && (
                <div className="flex gap-3 justify-start message-enter">
                  <div className="w-7 h-7 rounded-full bg-[#C8102E] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <svg className="w-3.5 h-3.5 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
                      <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
                    </svg>
                  </div>
                  <div className="px-4 py-3 rounded-[14px] rounded-bl-[4px] bg-[#FDFCFB] border border-[#E7E0D8]" style={{ borderWidth: '1.5px' }}>
                    <div className="flex gap-1 items-center h-5">
                      {[0, 0.2, 0.4].map(d => (
                        <div key={d} className="w-1.5 h-1.5 rounded-full bg-[#9A948E]" style={{ animation: `livePulse 1.2s ${d}s infinite` }} />
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {isStreaming && streamingContent && (
                <div className="flex gap-3 justify-start message-enter">
                  <div className="w-7 h-7 rounded-full bg-[#C8102E] flex items-center justify-center flex-shrink-0 mt-0.5">
                    <svg className="w-3.5 h-3.5 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="4" r="2"/><circle cx="18" cy="8" r="2"/><circle cx="20" cy="16" r="2"/>
                      <path d="M9 10a5 5 0 0 1 5 5v3.5a3.5 3.5 0 0 1-6.84 1.045Q6.52 17.48 4.46 16.84A3.5 3.5 0 0 1 5.5 10Z"/>
                    </svg>
                  </div>
                  <div className="max-w-[75%] px-4 py-3 rounded-[14px] rounded-bl-[4px] bg-[#FDFCFB] border border-[#E7E0D8] text-[14px] leading-[1.65] text-[#16120E]" style={{ borderWidth: '1.5px' }}>
                    <div className="prose-chat"><ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown></div>
                    <span className="typing-cursor" />
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input area */}
            <div className="flex-shrink-0 px-6 py-4 border-t border-[#E7E0D8] bg-[#FDFCFB]" style={{ borderTopWidth: '1.5px' }}>
              <div className="flex gap-3 items-end bg-[#FDFCFB] border border-[#E7E0D8] rounded-[14px] px-4 py-3" style={{ borderWidth: '1.5px' }}>
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={handleTextarea}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask a coding question… (Shift+Enter for new line)"
                  rows={1}
                  className="flex-1 resize-none outline-none bg-transparent text-[14px] text-[#16120E] placeholder-[#9A948E] leading-[1.6] max-h-[160px] font-sans"
                  style={{ fontFamily: "'DM Sans', sans-serif" }}
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isStreaming || isTyping || connStatus !== 'connected'}
                  className="w-9 h-9 rounded-[9px] bg-[#C8102E] hover:bg-[#9E0B24] disabled:opacity-40 flex items-center justify-center flex-shrink-0 transition-colors border-none cursor-pointer"
                >
                  <svg className="w-4 h-4 stroke-white fill-none" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                  </svg>
                </button>
              </div>
              <div className="text-[11px] text-[#9A948E] mt-2 text-center">
                Powered by Gemini 2.5 Pro · Prompts are evaluated for learning purposes
              </div>
            </div>
          </div>

          {/* Eval panel */}
          <div className="w-[380px] flex-shrink-0 overflow-hidden">
            <EvalSidebar evalData={evalData} isEvaluating={isEvaluating} turnCount={turnCount} />
          </div>
        </div>
      </div>
    </div>
  )
}
