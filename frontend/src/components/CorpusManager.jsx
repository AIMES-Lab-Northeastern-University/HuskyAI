import { useState, useEffect, useCallback, useRef } from 'react'
import { API_URL, authHeaders } from '../lib/api'

/* Reference corpus manager (Phase 2).
 *
 * Ground-truth material the evaluator scores student work against. Two things
 * the UI has to be honest about, because both are invisible otherwise:
 *
 *  - Indexing is asynchronous and can partially fail. Per-file status is shown
 *    rather than a single corpus-level spinner, so an instructor can see that
 *    three of four documents made it rather than assuming all did.
 *  - A corpus is only used for scoring once it is `ready`. Until then the
 *    evaluator falls back to rubric-only, and saying so plainly stops a
 *    "why did nothing change?" support thread.
 */

const STATUS_STYLE = {
  ready:    { bg: '#DCFCE7', fg: '#16A34A', label: 'Indexed' },
  pending:  { bg: '#FEF3E8', fg: '#D97706', label: 'Indexing…' },
  building: { bg: '#FEF3E8', fg: '#D97706', label: 'Indexing…' },
  failed:   { bg: '#FDE8EC', fg: '#C8102E', label: 'Failed' },
}

function StatusChip({ status }) {
  const s = STATUS_STYLE[status] || { bg: '#F7F3EE', fg: '#6B6560', label: status }
  return (
    <span className="text-[10px] font-bold px-2 py-0.5 rounded-[6px] flex-shrink-0"
          style={{ background: s.bg, color: s.fg }}>
      {s.label}
    </span>
  )
}

export default function CorpusManager({ classroomChallengeId, corpusId: initialCorpusId }) {
  const [corpus, setCorpus] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const fileRef = useRef(null)
  const pollRef = useRef(null)

  const load = useCallback(async (id) => {
    if (!id) return
    try {
      const r = await fetch(`${API_URL}/corpus/${id}`, { headers: authHeaders() })
      if (r.ok) setCorpus(await r.json())
    } catch (e) { console.error('could not load corpus', e) }
  }, [])

  useEffect(() => { if (initialCorpusId) load(initialCorpusId) }, [initialCorpusId, load])

  // Poll only while something is still indexing — an idle corpus needs no traffic.
  useEffect(() => {
    clearInterval(pollRef.current)
    if (!corpus) return
    const docs = corpus.documents || []
    // An empty corpus stays at "building" until the first upload, so polling on
    // status alone would hit the API every 2.5s forever and re-render the panel
    // for no reason. Only poll while a document is actually settling.
    const settling = docs.length > 0 &&
      (corpus.status === 'building' || docs.some(d => d.status === 'pending'))
    if (!settling) return
    pollRef.current = setInterval(() => load(corpus.id), 2500)
    return () => clearInterval(pollRef.current)
  }, [corpus, load])

  const create = async () => {
    setBusy(true); setError(null)
    try {
      const r = await fetch(`${API_URL}/corpus/assignments/${classroomChallengeId}`, {
        method: 'POST', headers: authHeaders(),
      })
      if (r.ok) setCorpus(await r.json())
      else setError((await r.json()).detail || 'Could not create corpus')
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  const upload = async (files) => {
    if (!corpus || !files?.length) return
    setBusy(true); setError(null)
    for (const file of files) {
      const fd = new FormData()
      fd.append('file', file)
      try {
        const r = await fetch(`${API_URL}/corpus/${corpus.id}/documents`, {
          method: 'POST', headers: authHeaders(), body: fd,
        })
        if (!r.ok) setError((await r.json()).detail || `Could not upload ${file.name}`)
      } catch (e) { setError(String(e)) }
    }
    await load(corpus.id)
    setBusy(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  const removeDoc = async (docId) => {
    await fetch(`${API_URL}/corpus/${corpus.id}/documents/${docId}`,
      { method: 'DELETE', headers: authHeaders() })
    load(corpus.id)
  }

  const detach = async () => {
    if (!window.confirm('Stop scoring against this corpus? The files are kept, and past scores stay valid.')) return
    await fetch(`${API_URL}/corpus/${corpus.id}`, { method: 'DELETE', headers: authHeaders() })
    setCorpus(null)
  }

  const docs = corpus?.documents || []

  if (!corpus) {
    return (
      <div className="border border-[#E7E0D8] rounded-[12px] p-4 bg-[#FDFCFB]" style={{ borderWidth: '1.5px' }}>
        <div className="text-[13px] font-bold text-[#16120E] mb-1">Reference corpus</div>
        <p className="text-[12px] text-[#6B6560] leading-relaxed mb-3">
          Attach ground-truth material and the evaluator will score student work
          against it, adding a grounding score. Without one, scoring is unchanged.
        </p>
        <button onClick={create} disabled={busy}
                className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] disabled:opacity-50 cursor-pointer">
          {busy ? 'Creating…' : 'Add a reference corpus'}
        </button>
        {error && <div className="text-[12px] text-[#C8102E] mt-2">{error}</div>}
      </div>
    )
  }

  const ready = docs.filter(d => d.status === 'ready').length
  const failed = docs.filter(d => d.status === 'failed')

  return (
    <div className="border border-[#E7E0D8] rounded-[12px] p-4 bg-[#FDFCFB]" style={{ borderWidth: '1.5px' }}>
      <div className="flex items-center gap-2 mb-1">
        <div className="text-[13px] font-bold text-[#16120E] flex-1">Reference corpus</div>
        <StatusChip status={corpus.status} />
      </div>

      <p className="text-[12px] text-[#6B6560] leading-relaxed mb-3">
        {docs.length === 0
          ? 'No documents yet. Upload one below — scoring stays rubric-only until then.'
          : corpus.status === 'ready'
            ? `The evaluator scores student work against these ${ready} document${ready === 1 ? '' : 's'}.`
            : 'Not in use yet — until indexing finishes, scoring falls back to the rubric only.'}
      </p>

      {docs.length > 0 && (
        <div className="flex flex-col gap-1.5 mb-3">
          {docs.map(d => (
            <div key={d.id} className="flex items-center gap-2 px-3 py-2 rounded-[8px] bg-[#F7F3EE] border border-[#E7E0D8]"
                 style={{ borderWidth: '1px' }}>
              <span className="text-[12px] text-[#16120E] flex-1 truncate">{d.filename}</span>
              <span className="text-[11px] text-[#9A948E] flex-shrink-0">
                {Math.max(1, Math.round((d.size_bytes || 0) / 1024))} KB
              </span>
              <StatusChip status={d.status} />
              <button onClick={() => removeDoc(d.id)} aria-label={`Remove ${d.filename}`}
                      className="text-[#9A948E] hover:text-[#C8102E] bg-transparent border-none cursor-pointer text-[14px] leading-none">
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {failed.length > 0 && (
        <div className="text-[12px] text-[#C8102E] mb-3">
          {failed.length} file{failed.length === 1 ? '' : 's'} could not be indexed and
          {failed.length === 1 ? ' is' : ' are'} not being scored against.
        </div>
      )}

      <div className="flex items-center gap-2">
        <input ref={fileRef} type="file" multiple
               accept=".txt,.md,.pdf,.csv,.json,.docx"
               onChange={e => upload(Array.from(e.target.files || []))}
               className="text-[12px] text-[#4A4440]" />
        {busy && <span className="text-[12px] text-[#9A948E]">Uploading…</span>}
      </div>
      <div className="text-[11px] text-[#9A948E] mt-1">
        Text, Markdown, PDF, CSV, JSON or DOCX. Up to 20MB each.
      </div>

      {error && <div className="text-[12px] text-[#C8102E] mt-2">{error}</div>}

      <button onClick={detach}
              className="mt-3 text-[11px] font-bold text-[#9A948E] hover:text-[#C8102E] bg-transparent border-none cursor-pointer p-0">
        Stop scoring against this corpus
      </button>
    </div>
  )
}
