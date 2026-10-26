import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, readApiError } from '../lib/api'
import { SubmissionModal, downloadAuthed, fmtScore, scoreColor } from './TeamSubmission'

/**
 * Instructor view of what every team handed in for a group assignment: one row
 * per team, one cell per session. A cell opens the team's document with a
 * grading form beside it; the instructor's score replaces the AI's as the
 * final score, and the AI's stays visible next to it.
 */

const STATUS = {
  not_started: { label: 'Not started', color: '#9A948E', bg: '#F7F3EE' },
  in_progress: { label: 'In progress', color: '#B45309', bg: '#FEF3C7' },
  submitted:   { label: 'Needs grading', color: '#1D4ED8', bg: '#DBEAFE' },
  graded:      { label: 'Graded', color: '#0D9488', bg: '#E6F7F6' },
}

function GradeForm({ data, setData, gradeUrl, onSaved }) {
  const [score, setScore] = useState(data.instructor_score ?? '')
  const [feedback, setFeedback] = useState(data.instructor_feedback ?? '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)

  const save = async (nextScore) => {
    const n = nextScore === '' || nextScore == null ? null : Number(nextScore)
    if (n != null && (Number.isNaN(n) || n < 0 || n > 100)) {
      setMsg({ error: true, text: 'Score must be between 0 and 100.' })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const r = await fetch(gradeUrl, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ score: n, feedback }),
      })
      if (!r.ok) throw new Error(await readApiError(r, 'Could not save the grade'))
      const d = await r.json()
      setData(prev => ({ ...prev, ...d }))
      setScore(d.instructor_score ?? '')
      setMsg({ error: false, text: 'Saved. Students see the grade and feedback.' })
      onSaved()
    } catch (e) {
      setMsg({ error: true, text: String(e.message || e) })
    } finally {
      setBusy(false)
    }
  }

  const lbl = { fontSize: '11px', fontWeight: 700, color: '#6B6560', textTransform: 'uppercase', letterSpacing: '0.6px' }
  return (
    <div style={{ padding: '18px', display: 'grid', gap: '14px' }}>
      <div style={{ fontSize: '14px', fontWeight: 700, color: '#16120E' }}>Grade this submission</div>

      <div style={{ padding: '10px 12px', background: '#fff', border: '1px solid #EFE8DF', borderRadius: '9px' }}>
        <div style={lbl}>AI team score</div>
        <div style={{ fontSize: '20px', fontWeight: 700, color: scoreColor(data.ai_score) }}>{fmtScore(data.ai_score)}</div>
        <div style={{ fontSize: '11px', color: '#9A948E' }}>
          {data.ai_score_range
            ? `Members ranged ${fmtScore(data.ai_score_range.min)}–${fmtScore(data.ai_score_range.max)}.`
            : 'PEI averaged over the session.'} Kept on record whatever you set.
        </div>
      </div>

      <label style={{ display: 'grid', gap: '5px' }}>
        <span style={lbl}>Your score (0–100)</span>
        <input type="number" min={0} max={100} step={0.5} value={score}
               placeholder={data.ai_score != null ? `AI: ${fmtScore(data.ai_score)}` : 'e.g. 80'}
               onChange={e => setScore(e.target.value)}
               style={{ fontSize: '15px', padding: '8px 10px', borderRadius: '8px', border: '1.5px solid #E7E0D8', width: '140px' }} />
        <span style={{ fontSize: '11px', color: '#9A948E' }}>Leave empty to keep the AI's score as the final score.</span>
      </label>

      <label style={{ display: 'grid', gap: '5px' }}>
        <span style={lbl}>Feedback to the team</span>
        <textarea rows={7} value={feedback} maxLength={5000} onChange={e => setFeedback(e.target.value)}
                  placeholder="What worked, what to improve…"
                  style={{ fontSize: '13px', padding: '8px 10px', borderRadius: '8px', border: '1.5px solid #E7E0D8', resize: 'vertical', fontFamily: 'inherit' }} />
      </label>

      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <button type="button" disabled={busy} onClick={() => save(score)}
                style={{ padding: '8px 14px', borderRadius: '8px', border: 'none', background: '#C8102E', color: '#fff', fontSize: '13px', fontWeight: 700, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1 }}>
          {busy ? 'Saving…' : 'Save grade'}
        </button>
        {data.instructor_score != null && (
          <button type="button" disabled={busy} onClick={() => save(null)}
                  style={{ padding: '8px 12px', borderRadius: '8px', border: '1.5px solid #E7E0D8', background: 'transparent', color: '#4A4440', fontSize: '12px', fontWeight: 600, cursor: busy ? 'default' : 'pointer' }}>
            Use AI score instead
          </button>
        )}
      </div>
      {msg && <div style={{ fontSize: '12px', color: msg.error ? '#C8102E' : '#0D9488' }}>{msg.text}</div>}

      <div style={{ fontSize: '12px', color: '#4A4440', borderTop: '1px solid #EFE8DF', paddingTop: '10px' }}>
        Final score: <b style={{ color: scoreColor(data.final_score) }}>{fmtScore(data.final_score)}</b>
        {data.instructor_score != null ? " (yours)" : data.final_score != null ? " (AI's)" : ''}
      </div>
    </div>
  )
}

export default function TeamSubmissionsPanel({ classroomId, challengeId }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)  // submission id
  const [zipBusy, setZipBusy] = useState(false)
  const [zipErr, setZipErr] = useState('')
  const [onlyUngraded, setOnlyUngraded] = useState(false)

  const base = `${API_URL}/classrooms/${classroomId}/challenges/${challengeId}`

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${base}/submissions`, { headers: authHeaders() })
      if (!r.ok) throw new Error(await readApiError(r, 'Could not load submissions'))
      setData(await r.json())
      setErr('')
    } catch (e) {
      setErr(String(e.message || e))
    }
  }, [base])

  useEffect(() => { load() }, [load])
  const close = useCallback(() => setOpen(null), [])

  const downloadAll = async () => {
    setZipBusy(true)
    setZipErr('')
    try { await downloadAuthed(`${base}/submissions-zip`, 'submissions.zip') } catch (e) { setZipErr(String(e.message || e)) } finally { setZipBusy(false) }
  }

  if (err) return <div style={{ fontSize: '13px', color: '#C8102E', marginTop: '10px' }}>{err}</div>
  if (!data) return <div style={{ fontSize: '13px', color: '#9A948E', marginTop: '10px' }}>Loading submissions…</div>

  const { teams, counts, challenge } = data
  const sessions = challenge.sessions
  const rows = onlyUngraded ? teams.filter(t => t.sessions.some(c => c.status === 'submitted')) : teams
  const btn = { padding: '5px 10px', borderRadius: '7px', border: '1.5px solid #E7E0D8', background: 'transparent', color: '#4A4440', fontSize: '11px', fontWeight: 600, cursor: 'pointer' }

  return (
    <div style={{ marginTop: '10px', padding: '12px', background: '#FBF9F6', borderRadius: '9px', border: '1px solid #F0EBE4' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '12px', color: '#6B6560' }}>
          <b style={{ color: '#16120E' }}>{counts.submitted}</b> submitted · <b style={{ color: '#16120E' }}>{counts.graded}</b> graded
          {' '}across {counts.teams} team{counts.teams === 1 ? '' : 's'}
          {sessions.length > 1 ? ` and ${sessions.length} sessions` : ''}.
          {' '}A team's document is submitted automatically when its session ends.
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: '11px', color: '#4A4440', display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input type="checkbox" checked={onlyUngraded} onChange={e => setOnlyUngraded(e.target.checked)} />
            Only needs grading
          </label>
          <button type="button" onClick={load} style={btn}>Refresh</button>
          <button type="button" onClick={downloadAll} disabled={zipBusy || counts.submitted === 0}
                  style={{ ...btn, background: '#16120E', color: '#fff', borderColor: '#16120E', opacity: zipBusy || counts.submitted === 0 ? 0.5 : 1 }}>
            {zipBusy ? 'Preparing…' : 'Download all PDFs'}
          </button>
        </div>
      </div>
      {zipErr && <div style={{ fontSize: '12px', color: '#C8102E', marginTop: '6px' }}>{zipErr}</div>}

      {teams.length === 0 ? (
        <div style={{ fontSize: '13px', color: '#9A948E', marginTop: '10px' }}>No teams yet. Create them under Manage teams.</div>
      ) : rows.length === 0 ? (
        <div style={{ fontSize: '13px', color: '#9A948E', marginTop: '10px' }}>Everything submitted has been graded.</div>
      ) : (
        <div style={{ overflowX: 'auto', marginTop: '10px' }}>
          <table style={{ width: '100%', borderCollapse: 'separate', borderSpacing: '0 6px', fontSize: '12px' }}>
            <thead>
              <tr style={{ textAlign: 'left', color: '#9A948E', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                <th style={{ padding: '0 10px', fontWeight: 700 }}>Team</th>
                {sessions.map(s => (
                  <th key={s.session_number} style={{ padding: '0 8px', fontWeight: 700, minWidth: '150px' }}>
                    Session {s.session_number}{s.title ? ` · ${s.title}` : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(t => (
                <tr key={t.id} style={{ background: '#fff' }}>
                  <td style={{ padding: '10px', borderRadius: '8px 0 0 8px', border: '1px solid #F0EBE4', borderRight: 'none', verticalAlign: 'top', minWidth: '160px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>{t.name}</div>
                    <div style={{ fontSize: '11px', color: '#6B6560' }}>{t.members.join(', ') || 'No members'}</div>
                  </td>
                  {t.sessions.map((c, i) => {
                    const st = STATUS[c.status]
                    const s = c.submission
                    const last = i === t.sessions.length - 1
                    return (
                      <td key={c.session_number} style={{ padding: '8px', border: '1px solid #F0EBE4', borderLeft: 'none', borderRight: last ? '1px solid #F0EBE4' : 'none', borderRadius: last ? '0 8px 8px 0' : 0, verticalAlign: 'top' }}>
                        <span style={{ display: 'inline-block', fontSize: '10px', fontWeight: 700, color: st.color, background: st.bg, borderRadius: '20px', padding: '2px 8px' }}>{st.label}</span>
                        {s && (
                          <>
                            <div style={{ marginTop: '6px', display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                              <span style={{ fontSize: '18px', fontWeight: 700, color: scoreColor(s.final_score) }}>{fmtScore(s.final_score)}</span>
                              <span style={{ fontSize: '11px', color: '#9A948E' }}>
                                {s.instructor_score != null
                                  ? <>yours · AI {fmtScore(s.ai_score)}</>
                                  : 'AI score'}
                              </span>
                            </div>
                            <div style={{ fontSize: '11px', color: '#9A948E' }}>{s.word_count} word{s.word_count === 1 ? '' : 's'}{s.has_feedback ? ' · feedback given' : ''}</div>
                            <button type="button" onClick={() => setOpen(s.id)}
                                    style={{ ...btn, marginTop: '6px', borderColor: '#C8102E', color: '#C8102E' }}>
                              {c.status === 'graded' ? 'View / edit grade' : 'Open & grade'}
                            </button>
                          </>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open && (
        <SubmissionModal
          loadUrl={`${base}/submissions/${open}`}
          pdfUrl={`${base}/submissions/${open}/pdf`}
          onClose={close}
          aside={(d, setD) => (
            <GradeForm key={d.id} data={d} setData={setD} gradeUrl={`${base}/submissions/${open}/grade`} onSaved={load} />
          )}
        />
      )}
    </div>
  )
}
