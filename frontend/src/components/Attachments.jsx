import { useCallback, useRef, useState } from 'react'
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

/** Fetch a team-chat file with the session token and save it. A plain link
 *  can't carry the Authorization header. */
async function downloadTeamFile(groupId, file) {
  const r = await fetch(`${API_URL}/groups/${groupId}/team-chat/attachments/${file.id}`, { headers: authHeaders() })
  if (!r.ok) throw new Error(`download failed (${r.status})`)
  const url = URL.createObjectURL(await r.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = file.filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** A file on a sent message. Clickable once the server has stored it (has an
 *  id and a groupId to fetch from); struck through if the server refused it. */
export function FileChip({ file, groupId, tone = 'light' }) {
  const [err, setErr] = useState('')
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
  if (!file.id || !groupId) {
    return <span className={`${base} ${colors}`}><ClipIcon className="w-3 h-3" /><span className="truncate">{name}</span></span>
  }
  return (
    <button type="button" title={err || `Download ${name}`}
            onClick={() => downloadTeamFile(groupId, file).then(() => setErr('')).catch(e => setErr(String(e.message || e)))}
            className={`${base} ${colors} cursor-pointer hover:underline`}>
      <ClipIcon className="w-3 h-3" /><span className="truncate">{name}</span>
      {err && <span className="text-[#C8102E] no-underline">!</span>}
    </button>
  )
}
