import React, { useState, useEffect, useRef, useCallback } from 'react'
import ChatInterface from './components/ChatInterface'
import EvalPanel from './components/EvalPanel'

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

export default function App() {
  const [messages, setMessages] = useState([])
  const [streamingContent, setStreamingContent] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isTyping, setIsTyping] = useState(false)
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [evalData, setEvalData] = useState(null)
  const [connectionStatus, setConnectionStatus] = useState('disconnected')
  const [turnCount, setTurnCount] = useState(0)

  const wsRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const streamBufferRef = useRef('')

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    setConnectionStatus('connecting')
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      setConnectionStatus('connected')
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
    }

    ws.onclose = () => {
      setConnectionStatus('disconnected')
      setIsStreaming(false)
      setIsTyping(false)
      setIsEvaluating(false)
      // Auto-reconnect after 3s
      reconnectTimerRef.current = setTimeout(connect, 3000)
    }

    ws.onerror = () => {
      setConnectionStatus('error')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleWsMessage(data)
      } catch (e) {
        console.error('Failed to parse message:', e)
      }
    }
  }, [])

  const handleWsMessage = (data) => {
    switch (data.type) {
      case 'typing':
        setIsTyping(true)
        setIsStreaming(false)
        streamBufferRef.current = ''
        setStreamingContent('')
        break

      case 'stream':
        setIsTyping(false)
        setIsStreaming(true)
        streamBufferRef.current += data.content
        setStreamingContent(prev => prev + data.content)
        break

      case 'done':
        setIsStreaming(false)
        setIsTyping(false)
        const finalResponse = data.full_response || streamBufferRef.current
        streamBufferRef.current = ''
        setStreamingContent('')
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: finalResponse }
        ])
        break

      case 'eval_start':
        setIsEvaluating(true)
        break

      case 'eval':
        setIsEvaluating(false)
        setEvalData(data.data)
        setTurnCount(prev => prev + 1)
        break

      case 'eval_error':
        setIsEvaluating(false)
        console.error('Eval error:', data.message)
        break

      case 'error':
        setIsStreaming(false)
        setIsTyping(false)
        setIsEvaluating(false)
        console.error('Server error:', data.message)
        break

      default:
        break
    }
  }

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const handleSend = useCallback((content) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    if (isStreaming || isTyping) return

    setMessages(prev => [...prev, { role: 'user', content }])
    wsRef.current.send(JSON.stringify({ type: 'message', content }))
  }, [isStreaming, isTyping])

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      {/* Top bar */}
      <header className="shrink-0 flex items-center gap-3 px-4 py-2 bg-surface-1 border-b border-surface-3 z-10">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-lg bg-white flex items-center justify-center shrink-0 overflow-hidden p-0.5">
            <img src="/logo.png" alt="Husky AI" className="w-full h-full object-contain" />
          </div>
          <span className="text-sm font-semibold text-slate-200">Husky AI</span>
          <span className="text-xs text-slate-600">—</span>
          <span className="text-xs text-slate-500">Be an AI-Ready Husky!</span>
        </div>
        <div className="ml-auto">
          <span className="text-xs px-2 py-0.5 rounded-full border border-[#C8102E]/30 text-[#C8102E] bg-[#C8102E]/10">
            Northeastern University
          </span>
        </div>
      </header>

      {/* Main layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Chat panel — 60% */}
        <div className="flex-1 min-w-0" style={{ flex: '0 0 60%' }}>
          <ChatInterface
            messages={messages}
            streamingContent={streamingContent}
            isStreaming={isStreaming}
            isTyping={isTyping}
            onSend={handleSend}
            connectionStatus={connectionStatus}
          />
        </div>

        {/* Eval panel — 40% */}
        <div className="shrink-0" style={{ flex: '0 0 40%', minWidth: '360px' }}>
          <EvalPanel
            evalData={evalData}
            isEvaluating={isEvaluating}
            turnCount={turnCount}
          />
        </div>
      </div>
    </div>
  )
}
