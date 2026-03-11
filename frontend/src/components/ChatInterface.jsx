import React, { useRef, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

function CodeBlock({ language, children }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(String(children)).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="relative group my-2">
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 z-10 text-xs px-2 py-1 rounded bg-surface-3 text-slate-400 opacity-0 group-hover:opacity-100 transition-opacity hover:text-slate-200"
      >
        {copied ? '✓ Copied' : 'Copy'}
      </button>
      <SyntaxHighlighter
        style={oneDark}
        language={language || 'text'}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: '8px',
          fontSize: '0.8rem',
          border: '1px solid #22222e',
          background: '#111118',
        }}
        codeTagProps={{ style: { fontFamily: 'JetBrains Mono, monospace' } }}
      >
        {String(children).replace(/\n$/, '')}
      </SyntaxHighlighter>
    </div>
  )
}

function MarkdownContent({ content }) {
  return (
    <div className="prose-dark text-sm text-slate-200 leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            return !inline && match ? (
              <CodeBlock language={match[1]}>{children}</CodeBlock>
            ) : (
              <code className={className} {...props}>{children}</code>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function Message({ role, content, isStreaming }) {
  const isUser = role === 'user'

  return (
    <div className={`flex gap-3 message-enter ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold
        ${isUser
          ? 'bg-accent-blue text-white'
          : 'bg-surface-3 text-accent-purple border border-surface-4'
        }`}
      >
        {isUser ? 'U' : 'AI'}
      </div>

      {/* Bubble */}
      <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${
        isUser
          ? 'bg-accent-blue text-white rounded-tr-sm'
          : 'bg-surface-2 border border-surface-3 rounded-tl-sm'
      }`}>
        {isUser ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
        ) : (
          <>
            <MarkdownContent content={content} />
            {isStreaming && <span className="typing-cursor" />}
          </>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 message-enter">
      <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold bg-surface-3 text-accent-purple border border-surface-4">
        AI
      </div>
      <div className="bg-surface-2 border border-surface-3 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex gap-1 items-center h-5">
          {[0, 1, 2].map(i => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

export default function ChatInterface({
  messages,
  streamingContent,
  isStreaming,
  isTyping,
  onSend,
  connectionStatus,
}) {
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)
  const [input, setInput] = useState('')

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, isTyping])

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed || isStreaming || isTyping) return
    onSend(trimmed)
    setInput('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e) => {
    setInput(e.target.value)
    // Auto-resize
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
  }

  const statusColor = {
    connected: 'bg-accent-green',
    connecting: 'bg-accent-amber animate-pulse',
    disconnected: 'bg-accent-red',
    error: 'bg-accent-red',
  }[connectionStatus] || 'bg-slate-500'

  return (
    <div className="h-full flex flex-col bg-surface-0">
      {/* Connection status bar */}
      <div className="flex items-center justify-end px-5 py-2 border-b border-surface-3 shrink-0 bg-surface-1">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${statusColor}`} />
          <span className="text-xs text-slate-500 capitalize">{connectionStatus}</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
        {messages.length === 0 && !isTyping && (
          <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-accent-blue/20 to-accent-purple/20 border border-surface-3 flex items-center justify-center text-3xl">
              💬
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-300">Start a conversation</h2>
              <p className="text-sm text-slate-500 mt-1 max-w-sm">
                Ask Claude a coding question. The evaluator in the right panel will analyze your prompting quality in real-time.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-2 w-full max-w-md mt-2">
              {[
                'Debug this Python function: def add(a, b): return a - b',
                'Help me implement a binary search tree in TypeScript',
                'What\'s the difference between useEffect and useLayoutEffect in React?',
              ].map((prompt, i) => (
                <button
                  key={i}
                  onClick={() => { setInput(prompt); textareaRef.current?.focus() }}
                  className="text-left text-xs text-slate-400 px-3 py-2.5 rounded-lg bg-surface-2 border border-surface-3 hover:border-surface-4 hover:text-slate-300 transition-all"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <Message
            key={i}
            role={msg.role}
            content={msg.content}
            isStreaming={false}
          />
        ))}

        {isTyping && !streamingContent && <TypingIndicator />}

        {streamingContent && (
          <Message
            role="assistant"
            content={streamingContent}
            isStreaming={true}
          />
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="shrink-0 px-4 py-4 border-t border-surface-3 bg-surface-1">
        <div className="flex gap-3 items-end">
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder="Ask Claude a coding question... (Shift+Enter for new line)"
              rows={1}
              disabled={connectionStatus !== 'connected'}
              className="w-full bg-surface-2 border border-surface-3 rounded-xl px-4 py-3 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-accent-blue/50 focus:ring-1 focus:ring-accent-blue/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ maxHeight: '160px', minHeight: '48px' }}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming || isTyping || connectionStatus !== 'connected'}
            className="w-11 h-11 rounded-xl bg-accent-blue hover:bg-blue-500 disabled:bg-surface-3 disabled:cursor-not-allowed flex items-center justify-center transition-all shrink-0"
          >
            {isStreaming || isTyping ? (
              <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-xs text-slate-600 mt-2 text-center">
          Press Enter to send · Shift+Enter for new line · Evaluation runs after each response
        </p>
      </div>
    </div>
  )
}
