import { useCallback, useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_URL, authHeaders, readApiError } from '../lib/api'

/**
 * A team's submission: the shared document frozen when the session ended, the
 * AI's team score, and the instructor's grade. The same view serves the
 * student (from the workspace once the session ends) and the instructor (from
 * the submissions panel, with a grading form passed in as `aside`).
 */

export function scoreColor(v) {
  if (v == null) return '#9A948E'
  if (v <= 40) return '#C8102E'
  if (v <= 65) return '#F97316'
  if (v <= 80) return '#0D9488'
  return '#16A34A'
}

export const fmtScore = (v) => (v == null ? '—' : String(Math.round(v * 10) / 10))

/** Fetch an authenticated file and save it under the server's filename. */
export async function downloadAuthed(url, fallbackName) {
  const r = await fetch(url, { headers: authHeaders() })
  if (!r.ok) throw new Error(await readApiError(r, 'Could not download'))
  const blob = await r.blob()
  const m = (r.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = m ? m[1] : fallbackName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

function ScoreTile({ label, value, note }) {
  return (
    <div className="flex-1 min-w-[120px] px-4 py-3">
      <div className="text-[10px] font-bold text-[#9A948E] uppercase tracking-[0.7px]">{label}</div>
      <div className="text-[24px] font-bold leading-tight" style={{ color: scoreColor(value) }}>{fmtScore(value)}</div>
      {note && <div className="text-[11px] text-[#9A948E]">{note}</div>}
    </div>
  )
}

export function SubmissionDocument({ data }) {
  const graded = data.instructor_score != null
  const submitted = data.submitted_at ? new Date(data.submitted_at + (data.submitted_at.endsWith('Z') ? '' : 'Z')) : null
  const ended = { timer_expired: 'time ran out', manual: 'ended by the team' }[data.end_reason]
  const empty = !(data.sections || []).some(s => (s.content || '').trim())

  return (
    <article className="max-w-[760px] mx-auto px-6 py-6">
      <div className="text-[11px] font-bold text-[#C8102E] uppercase tracking-[0.8px]">Team submission</div>
      <h1 className="text-[22px] font-bold text-[#16120E] leading-tight mt-1">{data.challenge_title}</h1>
      <div className="text-[14px] text-[#6B6560]">
        Session {data.session_number}{data.session_title ? `: ${data.session_title}` : ''}
      </div>
      <div className="text-[12px] text-[#6B6560] mt-3 space-y-0.5">
        <div><span className="font-bold text-[#4A4440]">{data.team_name}</span> · {data.members.join(', ')}</div>
        {submitted && <div>Submitted {submitted.toLocaleString()}{ended ? ` (${ended})` : ''}</div>}
      </div>

      <div className="flex flex-wrap mt-4 rounded-[10px] bg-[#F7F3EE] border border-[#EFE8DF]">
        {!data.scores_hidden && (
          <ScoreTile label="AI team score" value={data.ai_score}
            note={data.ai_score_range ? `members ${fmtScore(data.ai_score_range.min)}–${fmtScore(data.ai_score_range.max)}` : 'PEI'} />
        )}
        {data.my_pei != null && <ScoreTile label="Your own average" value={data.my_pei} note="PEI" />}
        <ScoreTile label="Instructor score" value={data.instructor_score}
          note={graded ? (data.graded_by_name ? `by ${data.graded_by_name}` : 'graded') : 'not graded yet'} />
        <ScoreTile label="Final score" value={data.final_score}
          note={graded ? "instructor's score" : data.final_score != null ? "AI's score" : ''} />
      </div>

      {data.per_student?.length > 0 && (
        <div className="mt-3 text-[12px] text-[#4A4440]">
          <span className="font-bold text-[#6B6560]">Each member's own average: </span>
          {data.per_student.map(p => `${p.name} ${fmtScore(p.avg_pei)} (${p.turns} turn${p.turns === 1 ? '' : 's'})`).join(' · ')}
        </div>
      )}

      {data.instructor_feedback && (
        <div className="mt-4 p-4 rounded-[10px] bg-[#E6F7F6] border border-[#C7E9E6]">
          <div className="text-[11px] font-bold text-[#0D9488] uppercase tracking-[0.7px] mb-1">Instructor feedback</div>
          <div className="prose-chat text-[13px] text-[#16120E]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.instructor_feedback}</ReactMarkdown>
          </div>
        </div>
      )}

      <hr className="my-6 border-0 border-t border-[#E7E0D8]" />

      {empty && <p className="text-[13px] italic text-[#9A948E]">The team's shared document was empty when the session ended.</p>}
      {(data.sections || []).map(s => (
        <section key={s.key} className="mb-6">
          {s.title && <h2 className="text-[17px] font-bold text-[#16120E]">{s.title}</h2>}
          {s.writers?.length > 0 && <div className="text-[11px] italic text-[#9A948E] mb-1">Written by {s.writers.join(', ')}</div>}
          {(s.content || '').trim()
            ? <div className="prose-chat text-[14px] text-[#16120E] leading-relaxed"><ReactMarkdown remarkPlugins={[remarkGfm]}>{s.content}</ReactMarkdown></div>
            : <div className="text-[13px] italic text-[#B5AFA8]">(left blank)</div>}
        </section>
      ))}
    </article>
  )
}

/**
 * Modal around a submission. `loadUrl` returns the JSON, `pdfUrl` the PDF.
 * `aside(data, setData)` renders beside the document (the grading form).
 */
export function SubmissionModal({ loadUrl, pdfUrl, onClose, aside }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [dlErr, setDlErr] = useState('')
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(loadUrl, { headers: authHeaders() })
        if (!r.ok) throw new Error(await readApiError(r, 'Could not open the submission'))
        const d = await r.json()
        if (!cancelled) setData(d)
      } catch (e) {
        if (!cancelled) setErr(String(e.message || e))
      }
    })()
    return () => { cancelled = true }
  }, [loadUrl])

  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const download = async () => {
    setDownloading(true)
    setDlErr('')
    try { await downloadAuthed(pdfUrl, 'submission.pdf') } catch (e) { setDlErr(String(e.message || e)) } finally { setDownloading(false) }
  }

  return (
    <div role="dialog" aria-modal="true" aria-label="Team submission" onClick={onClose}
         className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-4" style={{ background: 'rgba(22,18,14,0.45)' }}>
      <div onClick={e => e.stopPropagation()}
           className="bg-[#FDFCFB] rounded-[14px] flex flex-col w-full overflow-hidden"
           style={{ maxWidth: aside ? '1180px' : '880px', height: 'min(90vh, 1000px)', border: '1.5px solid #E7E0D8' }}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[#E7E0D8] flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span className="text-[14px] font-semibold text-[#16120E] truncate min-w-0">
            {data ? `${data.team_name} · Session ${data.session_number}` : 'Team submission'}
          </span>
          {dlErr && <span className="text-[11px] text-[#C8102E]">{dlErr}</span>}
          <button type="button" onClick={download} disabled={downloading || !data}
                  className="ml-auto px-3 py-1.5 text-[12px] font-bold text-[#4A4440] bg-[#F7F3EE] border border-[#E7E0D8] rounded-[8px] cursor-pointer flex-shrink-0 disabled:opacity-50">
            {downloading ? 'Preparing…' : 'Download PDF'}
          </button>
          <button type="button" onClick={onClose} aria-label="Close"
                  className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#C8102E] rounded-[8px] border-0 cursor-pointer flex-shrink-0">
            Close
          </button>
        </div>
        <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-auto md:overflow-hidden">
          <div className="md:flex-1 md:min-w-0 md:overflow-auto bg-white">
            {!data && !err && <div className="p-6 text-[13px] text-[#9A948E]">Opening…</div>}
            {err && <div className="p-6 text-[13px] text-[#C8102E]">{err}</div>}
            {data && <SubmissionDocument data={data} />}
          </div>
          {data && aside && (
            <div className="md:w-[340px] flex-shrink-0 md:overflow-auto border-t md:border-t-0 md:border-l border-[#E7E0D8] bg-[#FBF9F6]">
              {aside(data, setData)}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Shown to students once a team session has ended: the document is handed in,
 * here is what was submitted, and the grade once there is one.
 */
export function StudentSubmissionBar({ groupId, sessionNum }) {
  const [sub, setSub] = useState(null)
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), [])
  const base = `${API_URL}/groups/${groupId}/sessions/${sessionNum}/submission`

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(base, { headers: authHeaders() })
        if (r.ok && !cancelled) setSub(await r.json())
      } catch { /* the bar just stays hidden */ }
    })()
    return () => { cancelled = true }
  }, [base])

  if (!sub) return null
  return (
    <>
      <span className="text-[12px] text-[#4A4440]">
        ✓ Document submitted to your instructor
        {sub.instructor_score != null && <> · <b>Graded {fmtScore(sub.instructor_score)}</b></>}
      </span>
      <button type="button" onClick={() => setOpen(true)}
              className="px-3 py-1.5 text-[12px] font-bold text-white bg-[#0D9488] rounded-[8px] border-0 cursor-pointer">
        View final document
      </button>
      {open && <SubmissionModal loadUrl={base} pdfUrl={`${base}/pdf`} onClose={close} />}
    </>
  )
}
