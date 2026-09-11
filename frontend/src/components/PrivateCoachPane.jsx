import { useState, useEffect, useRef, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/**
 * The student's OWN coach thread inside a group session (/ws/coach).
 *
 * Privacy, client side:
 *   - it opens its own socket, authenticated with this browser's token; the
 *     server resolves the conversation from the authenticated user's id, so
 *     there is no conversation id in the URL to tamper with
 *   - nothing here reads or writes shared state. Messages live in this
 *     component's own useState and are discarded on unmount, so a different
 *     student logging in cannot inherit them
 *   - the socket is closed and messages cleared whenever the token or session
 *     changes, so a re-login never shows the previous user's thread
 *
 * Visually distinct from the team coach on purpose: the shared thread is the
 * team's, this one is not, and a student mixing them up would post something
 * private into the shared conversation or vice versa.
 */
const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

function CoachMessage({ role, content }) {
  const isSelf = role === 'user'
  return (
    <div className={`flex ${isSelf ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[78%] px-4 py-3 rounded-[14px] text-[14px] leading-[1.65] ${
          isSelf
            ? 'bg-[#7C3AED] text-white'
            : 'bg-[#FDFCFB] border border-[#E7E0D8] text-[#16120E]'
        }`}
        style={isSelf ? undefined : { borderWidth: '1.5px' }}
      >
        {isSelf ? content : (
          <div className="prose-sm">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}

export default function PrivateCoachPane({ groupId, sessionNum, token, roleLabel }) {
  const [messages, setMessages] = useState([])
  const [streaming, setStreaming] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [status, setStatus] = useState('disconnected')
  const [input, setInput] = useState('')

  const wsRef = useRef(null)
  const bufRef = useRef('')
  const endRef = useRef(null)

  const handle = useCallback((data) => {
    switch (data.type) {
      case 'session_init':
        setStatus('connected')
        break
      case 'history':
        if (Array.isArray(data.messages)) {
          setMessages(data.messages.filter(
            m => m && typeof m.role === 'string' && typeof m.content === 'string'))
        }
        break
      case 'typing':
        setIsTyping(true); bufRef.current = ''; setStreaming('')
        break
      case 'stream':
        setIsTyping(false)
        bufRef.current += data.content
        setStreaming(prev => prev + data.content)
        break
      case 'done':
        setIsTyping(false)
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: data.full_response || bufRef.current },
        ])
        bufRef.current = ''; setStreaming('')
        break
      case 'error':
        setIsTyping(false)
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: `⚠️ ${data.message || 'Coach error'}` },
        ])
        break
      default:
        break
    }
  }, [])

  useEffect(() => {
    if (!token || !groupId) return
    // Clear anything from a previous identity/session before connecting.
    setMessages([]); setStreaming(''); bufRef.current = ''
    const qs = new URLSearchParams({ token, group_id: groupId, session_num: String(sessionNum) })
    if (roleLabel) qs.set('role', roleLabel)
    const ws = new WebSocket(`${WS_BASE}/coach?${qs.toString()}`)
    wsRef.current = ws
    ws.onopen = () => setStatus('connected')
    ws.onclose = () => setStatus('disconnected')
    ws.onerror = () => setStatus('disconnected')
    ws.onmessage = (e) => { try { handle(JSON.parse(e.data)) } catch { /* ignore */ } }
    return () => {
      ws.close()
      wsRef.current = null
      setMessages([])       // never leave one user's thread in memory for the next
      setStreaming('')
    }
  }, [token, groupId, sessionNum, roleLabel, handle])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming])

  const send = () => {
    const content = input.trim()
    if (!content || wsRef.current?.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ type: 'message', content, attachments: [] }))
    setInput('')
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden min-w-0">
      {/* Deliberately purple-accented: the team coach is red. A student must
          never be unsure which thread they are typing into. */}
      <div
        className="flex-shrink-0 px-6 py-3 border-b border-[#E7E0D8] flex items-center gap-2"
        style={{ borderBottomWidth: '1.5px', background: '#F8F5FF' }}
      >
        <span className="w-2 h-2 rounded-full" style={{ background: '#7C3AED' }} />
        <span className="text-[12px] font-bold text-[#16120E]">Your private coach</span>
        <span className="text-[11px] text-[#9A948E]">
          Only you can see this — teammates cannot
        </span>
        {roleLabel && (
          <span className="text-[10px] font-bold px-[8px] py-[2px] rounded-[20px] bg-[#EDE9FE] text-[#7C3AED]">
            {roleLabel}
          </span>
        )}
        <span className="ml-auto text-[11px] text-[#9A948E]">
          {status === 'connected' ? 'Connected' : 'Connecting…'}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6 flex flex-col gap-4">
        {messages.length === 0 && !streaming && (
          <div className="flex-1 flex flex-col items-center justify-center text-center text-[#9A948E] text-[13px]">
            <p>This is your own coach.</p>
            <p className="mt-1">Nothing you say here is shared with your team.</p>
          </div>
        )}
        {messages.map((m, i) => (
          <CoachMessage key={i} role={m.role} content={m.content} />
        ))}
        {isTyping && (
          <div className="px-4 py-3 rounded-[14px] bg-[#FDFCFB] border border-[#E7E0D8] text-[#9A948E] text-[13px] self-start"
               style={{ borderWidth: '1.5px' }}>
            Coach is thinking…
          </div>
        )}
        {streaming && <CoachMessage role="assistant" content={streaming} />}
        <div ref={endRef} />
      </div>

      <div className="flex-shrink-0 px-6 py-4 border-t border-[#E7E0D8] bg-[#FDFCFB]"
           style={{ borderTopWidth: '1.5px' }}>
        <div className="flex items-end gap-2 border border-[#E7E0D8] rounded-[12px] px-3 py-2"
             style={{ borderWidth: '1.5px' }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
            rows={1}
            placeholder="Ask your own coach…"
            className="flex-1 resize-none outline-none bg-transparent text-[14px] text-[#16120E] placeholder-[#9A948E] leading-[1.6] max-h-[160px]"
          />
          <button
            type="button"
            onClick={send}
            disabled={!input.trim() || status !== 'connected'}
            className="text-[12px] font-semibold px-3 py-1.5 rounded-[8px] text-white disabled:opacity-40"
            style={{ background: '#7C3AED' }}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
