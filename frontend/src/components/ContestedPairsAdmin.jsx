import { useCallback, useEffect, useState } from 'react'
import { authHeaders, formatApiErrorDetail } from '../lib/api'

/**
 * Instructor authoring of contested pairs for one team.
 *
 * A pair is two divergent answers to the same subproblem (an artifact
 * section): one presented as a teammate's, one as the coach's. It is shown to
 * one student, and which answer they adopt — and whether they opened either
 * first, derived from the read log — is the measurement.
 *
 * Two rules this form exists to hold:
 *  - The teammate's answer is always option A and the coach's always option B.
 *    The fields are named by source, not by letter, so they cannot be swapped;
 *    if the order varied, "adopted A" would mean different things in different
 *    rows.
 *  - Students see the two answers WITHOUT labels. The labels below are for the
 *    instructor only. Do not add them to the student view: that would measure
 *    trust in the label rather than in the work.
 */

const CARD = {
  background: '#FDFCFB',
  borderRadius: '14px',
  border: '1.5px solid #E7E0D8',
  padding: '18px',
}

const INPUT = {
  fontSize: '12px', padding: '6px 8px', borderRadius: '7px',
  border: '1.5px solid #E7E0D8', background: '#fff', color: '#16120E',
}

const MUTED = '#9A948E'

const ADOPTED_LABEL = {
  a: "Took the teammate's answer",
  b: "Took the coach's answer",
  merged: 'Merged both',
  neither: 'Took neither',
}

const emptyForm = (sections) => ({
  session_number: 1,
  subproblem_key: sections[0]?.key || '',
  surfaced_to_user_id: '',
  teammate_answer: '',
  coach_answer: '',
  better_option: '',
})

export default function ContestedPairsAdmin({ baseUrl, team, totalSessions = 1, sections = [] }) {
  const [pairs, setPairs] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [form, setForm] = useState(() => emptyForm(sections))
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const url = `${baseUrl}/${team.id}/contested-pairs`
  const members = team.members || []
  const nameOf = (uid) => members.find(m => m.user_id === uid)?.name || 'Former member'
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await fetch(url, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) setErr(formatApiErrorDetail(d.detail))
      else setPairs(d.pairs || [])
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }, [url])

  useEffect(() => { load() }, [load])

  const ready = form.subproblem_key.trim() && form.surfaced_to_user_id
    && form.teammate_answer.trim() && form.coach_answer.trim()

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          session_number: Number(form.session_number),
          subproblem_key: form.subproblem_key.trim(),
          surfaced_to_user_id: form.surfaced_to_user_id,
          teammate_answer: form.teammate_answer,
          coach_answer: form.coach_answer,
          better_option: form.better_option || null,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setMsg(formatApiErrorDetail(d.detail)); return }
      setMsg('Added.')
      // Keep session, section and student for writing the next pair quickly.
      setForm(f => ({ ...f, teammate_answer: '', coach_answer: '', better_option: '' }))
      await load()
    } catch {
      setMsg('Network error')
    } finally {
      setSaving(false)
    }
  }

  const remove = async (pairId) => {
    setMsg('')
    try {
      const r = await fetch(`${url}/${pairId}`, { method: 'DELETE', headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) setMsg(formatApiErrorDetail(d.detail))
      await load()
    } catch {
      setMsg('Network error')
    }
  }

  const label = { fontSize: '12px', color: '#4A4440', display: 'grid', gap: '4px' }

  return (
    <div style={{ ...CARD, marginTop: '10px' }}>
      <div style={{ fontSize: '11px', fontWeight: 700, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
        Contested answers
      </div>
      <div style={{ fontSize: '12px', color: '#6B6560', lineHeight: 1.6, marginBottom: '12px' }}>
        Write two conflicting answers to one section. The chosen student sees both, side by side
        and <strong>unlabelled</strong>, and picks one. They see it when they are next in that session.
      </div>

      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <label style={label}>
          Session
          <select aria-label="Session" value={form.session_number} onChange={set('session_number')} style={INPUT}>
            {Array.from({ length: totalSessions }, (_, i) => (
              <option key={i + 1} value={i + 1}>Session {i + 1}</option>
            ))}
          </select>
        </label>
        <label style={label}>
          Section
          {sections.length > 0 ? (
            <select aria-label="Section" value={form.subproblem_key} onChange={set('subproblem_key')} style={INPUT}>
              {sections.map(s => <option key={s.key} value={s.key}>{s.title}</option>)}
            </select>
          ) : (
            <input aria-label="Section" value={form.subproblem_key} onChange={set('subproblem_key')}
                   placeholder="e.g. whole-doc" style={INPUT} />
          )}
        </label>
        <label style={label}>
          Shown to
          <select aria-label="Shown to" value={form.surfaced_to_user_id} onChange={set('surfaced_to_user_id')} style={INPUT}>
            <option value="">Pick a student…</option>
            {members.map(m => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
          </select>
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '10px', marginBottom: '8px' }}>
        <label style={label}>
          Teammate's answer <span style={{ color: MUTED }}>(for you only; not shown to the student)</span>
          <textarea aria-label="Teammate's answer" rows={4} value={form.teammate_answer}
                    onChange={set('teammate_answer')} style={{ ...INPUT, resize: 'vertical' }} />
        </label>
        <label style={label}>
          Coach's answer <span style={{ color: MUTED }}>(for you only; not shown to the student)</span>
          <textarea aria-label="Coach's answer" rows={4} value={form.coach_answer}
                    onChange={set('coach_answer')} style={{ ...INPUT, resize: 'vertical' }} />
        </label>
      </div>

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '10px', flexWrap: 'wrap' }}>
        <label style={label}>
          Which answer is correct?
          <select aria-label="Correct answer" value={form.better_option} onChange={set('better_option')} style={INPUT}>
            <option value="">Not sure / no right answer</option>
            <option value="a">The teammate's</option>
            <option value="b">The coach's</option>
          </select>
        </label>
        <button type="button" onClick={save} disabled={!ready || saving}
          style={{ padding: '7px 14px', borderRadius: '8px', border: 'none', background: '#16120E', color: '#fff',
                   fontSize: '12px', fontWeight: 600, cursor: !ready || saving ? 'default' : 'pointer',
                   opacity: !ready || saving ? 0.5 : 1 }}>
          {saving ? 'Adding…' : 'Add contested pair'}
        </button>
        {msg && <span style={{ fontSize: '12px', color: msg === 'Added.' ? '#6B6560' : '#C8102E' }}>{msg}</span>}
      </div>

      <div style={{ marginTop: '16px' }}>
        {loading ? (
          <div style={{ fontSize: '12px', color: MUTED }}>Loading…</div>
        ) : err ? (
          <div style={{ fontSize: '12px', color: '#C8102E' }}>{err}</div>
        ) : pairs.length === 0 ? (
          <div style={{ fontSize: '12px', color: MUTED }}>No contested pairs for this team yet.</div>
        ) : (
          <div style={{ display: 'grid', gap: '8px' }}>
            {pairs.map(p => (
              <div key={p.pair_id} data-testid="pair-row"
                style={{ fontSize: '12px', color: '#4A4440', padding: '8px 10px', background: '#fff', border: '1px solid #F0EBE4', borderRadius: '8px' }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                  <strong>Session {p.session_number}</strong>
                  <span style={{ fontFamily: 'monospace', color: MUTED }}>{p.subproblem_key}</span>
                  <span>→ {nameOf(p.surfaced_to_user_id)}</span>
                  <span style={{ marginLeft: 'auto', fontWeight: 600, color: p.adopted ? '#15803D' : MUTED }}>
                    {p.adopted ? ADOPTED_LABEL[p.adopted] || p.adopted : p.surfaced ? 'Shown, waiting' : 'Not shown yet'}
                  </span>
                  {p.uninspected_adoption && (
                    <span style={{ color: '#C8102E', fontWeight: 600 }}>without opening either</span>
                  )}
                  {!p.surfaced && (
                    <button type="button" onClick={() => remove(p.pair_id)}
                      style={{ border: '1px solid #F9BFCA', background: 'transparent', color: '#C8102E', borderRadius: '6px', fontSize: '11px', padding: '2px 8px', cursor: 'pointer' }}>
                      Delete
                    </button>
                  )}
                </div>
                <div style={{ color: MUTED, marginTop: '4px' }}>
                  Teammate: {p.teammate_answer.slice(0, 80)}{p.teammate_answer.length > 80 ? '…' : ''}
                  {' · '}Coach: {p.coach_answer.slice(0, 80)}{p.coach_answer.length > 80 ? '…' : ''}
                  {p.better_option && ` · Correct: ${p.better_option === 'a' ? 'teammate' : 'coach'}`}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
