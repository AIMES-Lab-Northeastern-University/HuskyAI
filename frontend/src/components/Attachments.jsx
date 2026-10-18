import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API_URL, authHeaders } from '../lib/api'

// Client-side mirror of the backend caps (backend/main.py _MAX_ATTACH_*). A
// message travels as one websocket frame, so files are capped per message;
// the server stays authoritative and reports anything it drops.
export const ATTACH_ACCEPT = '.pdf,.docx,.txt,.md,.csv,.png,.jpg,.jpeg,.webp,.gif'
const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_MESSAGE_BYTES = 11 * 1024 * 1024
const MAX_FILES_PER_MESSAGE = 5

const ALLOWED_EXT = new Set(ATTACH_ACCEPT.split(','))

/** Pending files for one composer: [{ name, mime, data(base64), size }]. */
export function usePendingFiles() {
  const [files, setFiles] = useState([])
  const [notice, setNotice] = useState('')
  // Files picked but still being read count toward the caps too, so two
  // quick picks can't overshoot them before the first read finishes.
  const committed = useRef({ count: 0, bytes: 0 })

  const add = useCallback((fileList) => {
    const picked = Array.from(fileList || [])
    if (!picked.length) return
    const problems = []
    for (const file of picked) {
      const ext = file.name.includes('.') ? file.name.slice(file.name.lastIndexOf('.')).toLowerCase() : ''
      if (!ALLOWED_EXT.has(ext)) { problems.push(`"${file.name}" isn't a supported file type.`); continue }
      if (file.size > MAX_FILE_BYTES) { problems.push(`"${file.name}" is over ${MAX_FILE_BYTES / 1024 / 1024} MB.`); continue }
      if (committed.current.count >= MAX_FILES_PER_MESSAGE) { problems.push(`Up to ${MAX_FILES_PER_MESSAGE} files per message.`); break }
      if (committed.current.bytes + file.size > MAX_MESSAGE_BYTES) {
        problems.push(`One message can carry up to ${MAX_MESSAGE_BYTES / 1024 / 1024} MB of files.`); break
      }
      committed.current = { count: committed.current.count + 1, bytes: committed.current.bytes + file.size }
      const reader = new FileReader()
      reader.onload = () => {
        const data = String(reader.result || '').split(',')[1] || ''
        setFiles(cur => [...cur, { name: file.name, mime: file.type || 'application/octet-stream', data, size: file.size }])
      }
      reader.readAsDataURL(file)
    }
    setNotice(problems[0] || '')
  }, [])

  const remove = useCallback(idx => {
    const gone = files[idx]
    if (!gone) return
    committed.current = { count: committed.current.count - 1, bytes: committed.current.bytes - gone.size }
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }, [files])
  const clear = useCallback(() => { committed.current = { count: 0, bytes: 0 }; setFiles([]); setNotice('') }, [])
  const toWire = useCallback(() => files.map(f => ({ filename: f.name, mime_type: f.mime, data: f.data })), [files])

  return { files, add, remove, clear, toWire, notice, setNotice }
}

const ClipIcon = ({ className = 'w-4 h-4' }) => (
  <svg className={`${className} stroke-current fill-none`} viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
)

/** Paperclip button with its own hidden file input. */
export function AttachButton({ onFiles, disabled, label = 'Attach a file', compact = false }) {
  const inputRef = useRef(null)
  return (
    <>
      <input ref={inputRef} type="file" multiple accept={ATTACH_ACCEPT} className="hidden"
             onChange={e => { onFiles(e.target.files); e.target.value = '' }} />
      <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}
              title={`${label} (PDF, DOCX, TXT, MD, CSV or image · max 10 MB)`} aria-label={label}
              className={`${compact ? 'w-8 h-8 rounded-[8px]' : 'w-10 h-10 rounded-[12px]'} flex items-center justify-center flex-shrink-0 bg-[#F7F3EE] hover:bg-[#EDEAE4] text-[#6B6560] border border-[#E7E0D8] disabled:opacity-40 cursor-pointer`}
              style={{ borderWidth: '1.5px' }}>
        <ClipIcon className={compact ? 'w-3.5 h-3.5' : 'w-4 h-4'} />
      </button>
    </>
  )
}

/** Chips for files picked but not yet sent, each removable. */
export function PendingFiles({ files, onRemove, notice }) {
  if (!files.length && !notice) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-2">
      {files.map((f, i) => (
        <span key={i} className="inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-[8px] bg-[#F7F3EE] border border-[#E7E0D8] text-[11px] text-[#4A4440]">
          <ClipIcon className="w-3 h-3" />
          <span className="max-w-[160px] truncate">{f.name}</span>
          <button type="button" onClick={() => onRemove(i)} aria-label={`Remove ${f.name}`}
                  className="w-4 h-4 rounded-full flex items-center justify-center text-[#9A948E] hover:text-[#C8102E] bg-transparent border-0 cursor-pointer">×</button>
        </span>
      ))}
      {notice && <span className="text-[11px] text-[#C8102E]">{notice}</span>}
    </div>
  )
}

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const TEXT_MIME = new Set(['text/plain', 'text/markdown', 'text/csv'])

// The type a preview needs, from the extension (the browser's own guess for a
// picked file is often empty). Mirrors backend _TEAM_CHAT_MIME_BY_EXT.
const MIME_BY_EXT = {
  '.pdf': 'application/pdf', '.docx': DOCX_MIME, '.txt': 'text/plain', '.md': 'text/markdown',
  '.csv': 'text/csv', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.webp': 'image/webp', '.gif': 'image/gif',
}
const mimeFor = name => MIME_BY_EXT[(name.match(/\.[^.]+$/)?.[0] || '').toLowerCase()] || 'application/octet-stream'

/** Where a previewed file's bytes come from: a team-chat file is fetched from
 *  its members-only endpoint (with the session token — a plain link can't carry
 *  the Authorization header); a coach-chat file is already on the page as
 *  base64, from the chat history or from the student's own pick. */
function teamSource(groupId, file) {
  const base = `${API_URL}/groups/${groupId}/team-chat/attachments/${file.id}`
  return {
    name: file.filename,
    mime: file.mime_type,
    blob: async () => {
      const r = await fetch(base, { headers: authHeaders() })
      if (!r.ok) throw new Error(`Could not load the file (${r.status})`)
      return r.blob()
    },
    docxText: async () => {
      const r = await fetch(`${base}/text`, { headers: authHeaders() })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body.detail || `Could not load the file (${r.status})`)
      return body.text
    },
  }
}

function localSource(file) {
  const name = file.filename || file.name
  const mime = mimeFor(name)
  return {
    name,
    mime,
    blob: async () => {
      const bin = atob(file.data)
      const bytes = new Uint8Array(bin.length)
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
      return new Blob([bytes], { type: mime })
    },
    docxText: async () => {
      const r = await fetch(`${API_URL}/files/docx-text`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ data: file.data }),
      })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(body.detail || `Could not read the file (${r.status})`)
      return body.text
    },
  }
}

async function downloadSource(source) {
  const url = URL.createObjectURL(await source.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = source.name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** A file opened inside the app. Images and PDFs are shown from the file
 *  itself, text files as plain text, and Word documents as the text the server
 *  extracts (browsers can't display .docx). Nothing is rendered as a page: only
 *  these types are accepted, and text is shown, not parsed. */
function FilePreview({ source, onClose }) {
  const [view, setView] = useState({ state: 'loading' })
  const [downloadError, setDownloadError] = useState('')

  useEffect(() => {
    let cancelled = false
    let url = null
    ;(async () => {
      try {
        if (source.mime === DOCX_MIME) {
          const text = await source.docxText()
          if (!cancelled) setView({ state: 'text', text: text || '(This document has no text.)' })
          return
        }
        const blob = await source.blob()
        if (TEXT_MIME.has(source.mime)) {
          const text = await blob.text()
          if (!cancelled) setView({ state: 'text', text })
          return
        }
        if (source.mime !== 'application/pdf' && !source.mime.startsWith('image/')) {
          if (!cancelled) setView({ state: 'error', message: "This file can't be previewed. Download it instead." })
          return
        }
        // Typed explicitly so the browser picks its image or PDF viewer.
        url = URL.createObjectURL(new Blob([blob], { type: source.mime }))
        if (!cancelled) setView({ state: source.mime === 'application/pdf' ? 'pdf' : 'image', url })
      } catch (e) {
        if (!cancelled) setView({ state: 'error', message: String(e.message || e) })
      }
    })()
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [source])

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div role="dialog" aria-modal="true" aria-label={`Preview of ${source.name}`} onClick={onClose}
         className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(22,18,14,0.45)' }}>
      <div onClick={e => e.stopPropagation()}
           className="bg-[#FDFCFB] rounded-[14px] flex flex-col w-full overflow-hidden"
           style={{ maxWidth: '900px', height: 'min(85vh, 900px)', border: '1.5px solid #E7E0D8' }}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[#E7E0D8] flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <ClipIcon className="w-4 h-4 text-[#6B6560]" />
          <span className="text-[14px] font-semibold text-[#16120E] truncate min-w-0">{source.name}</span>
          {downloadError && <span className="text-[11px] text-[#C8102E]">{downloadError}</span>}
          <button type="button" onClick={() => downloadSource(source).then(() => setDownloadError('')).catch(e => setDownloadError(String(e.message || e)))}
                  className="ml-auto px-3 py-1.5 text-[12px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer flex-shrink-0">
            Download
          </button>
          <button type="button" onClick={onClose} aria-label="Close preview"
                  className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] border-0 cursor-pointer flex-shrink-0">
            Close
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-auto bg-white">
          {view.state === 'loading' && <div className="p-6 text-[13px] text-[#9A948E]">Opening…</div>}
          {view.state === 'error' && <div className="p-6 text-[13px] text-[#C8102E]">{view.message}</div>}
          {view.state === 'text' && (
            <pre className="p-5 m-0 text-[13px] leading-relaxed text-[#16120E] whitespace-pre-wrap break-words font-mono">{view.text}</pre>
          )}
          {view.state === 'image' && (
            <div className="h-full flex items-center justify-center p-4">
              <img src={view.url} alt={source.name} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
            </div>
          )}
          {view.state === 'pdf' && <iframe src={view.url} title={source.name} className="w-full h-full border-0" />}
        </div>
      </div>
    </div>
  )
}

/** A file on a sent message, opening a preview. A coach-chat file carries its
 *  own bytes; a team-chat file opens once the server has stored it (has an id
 *  and a groupId to fetch from). Struck through if it was refused. */
export function FileChip({ file, groupId, tone = 'light' }) {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const source = useMemo(() => (file.data ? localSource(file)
    : file.id && groupId ? teamSource(groupId, file) : null), [file, groupId])
  const name = file.filename || file.name
  const base = 'inline-flex items-center gap-1 px-2 py-0.5 rounded-[6px] border text-[11px] max-w-full'
  if (file.failed) {
    return (
      <span className={`${base} bg-[#FDE8EC] border-[#F2B8C2] text-[#C8102E] line-through`} title={`Not sent: ${file.reason || 'refused'}`}>
        <ClipIcon className="w-3 h-3" /><span className="truncate">{name}</span>
      </span>
    )
  }
  const colors = tone === 'dark' ? 'bg-white/15 border-white/30 text-white' : 'bg-white border-[#D8D0C6] text-[#4A4440]'
  if (!source) {
    return <span className={`${base} ${colors}`}><ClipIcon className="w-3 h-3" /><span className="truncate">{name}</span></span>
  }
  return (
    <>
      <button type="button" title={`Open ${name}`} onClick={() => setOpen(true)}
              className={`${base} ${colors} cursor-pointer hover:underline`}>
        <ClipIcon className="w-3 h-3" /><span className="truncate">{name}</span>
      </button>
      {open && <FilePreview source={source} onClose={close} />}
    </>
  )
}
