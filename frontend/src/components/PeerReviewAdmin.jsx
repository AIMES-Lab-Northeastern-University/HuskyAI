import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

/**
 * Instructor controls for routed peer review.
 *
 * ReviewPairingsEditor — who reviews whose work, set before the session, for
 * the "I pick each student's reviewer" policy (instructor_assigned). Reviews
 * still go out the instant a section is saved; the instructor is never in the
 * loop per review, because making review latency depend on instructor
 * attention would distort the read-timing data the outcomes are derived from.
 * A student left without a reviewer gets no review — the server never falls
 * back to round-robin — so the editor says so rather than hiding it.
 *
 * PeerReviewsPanel — every review in the team's sessions with its derived
 * outcome, and a way to move a pending one to another teammate (e.g. the
 * reviewer went quiet). Works under every policy. The moved review keeps its
 * history: the old row reads as "Reassigned", not as a skipped check.
 */

const CARD = {
  background: '#FDFCFB',
  borderRadius: '14px',
  border: '1.5px solid #E7E0D8',
  padding: '18px',
}

const SECTION_LABEL = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.7px',
  marginBottom: '12px',
}

const SELECT = {
  fontSize: '12px', padding: '5px 8px', borderRadius: '7px',
  border: '1.5px solid #E7E0D8', background: '#fff', color: '#4A4440', maxWidth: '220px',
}

const MUTED = '#9A948E'

export function ReviewPairingsEditor({ baseUrl, team, onSaved }) {
  const toMap = (pairings) => Object.fromEntries((pairings || []).map(p => [p.author_user_id, p.reviewer_user_id]))
  const [draft, setDraft] = useState(() => toMap(team.review_pairings))
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  // Re-seed when the saved pairings change underneath (a member removed
  // clears their pairings server-side).
  const savedKey = JSON.stringify(team.review_pairings || [])
  useEffect(() => { setDraft(toMap(team.review_pairings)) }, [savedKey])

  const members = team.members || []
  const saved = toMap(team.review_pairings)
  const dirty = members.some(m => (draft[m.user_id] || '') !== (saved[m.user_id] || ''))
  const unpaired = members.filter(m => !draft[m.user_id])

  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const pairings = Object.entries(draft)
        .filter(([, r]) => r)
        .map(([author_user_id, reviewer_user_id]) => ({ author_user_id, reviewer_user_id }))
      const r = await fetch(`${baseUrl}/${team.id}/review-pairings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ pairings }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) setMsg(formatApiErrorDetail(d.detail))
      else { setMsg('Saved.'); onSaved?.() }
    } catch {
      setMsg('Network error')
    } finally {
      setSaving(false)
    }
  }

  if (members.length < 2) {
    return <div style={{ fontSize: '12px', color: MUTED, marginTop: '8px' }}>Add at least two students to pick reviewers.</div>
  }

  return (
    <div style={{ marginTop: '10px', padding: '10px', background: '#FBF9F6', borderRadius: '8px', border: '1px solid #F0EBE4' }}>
      <div style={{ fontSize: '12px', fontWeight: 600, color: '#16120E', marginBottom: '8px' }}>Reviewers</div>
      <div style={{ display: 'grid', gap: '6px' }}>
        {members.map(m => (
          <label key={m.user_id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4A4440' }}>
            <span style={{ minWidth: '170px' }}>{m.name}'s work is reviewed by</span>
            <select
              aria-label={`Reviewer for ${m.name}`}
              value={draft[m.user_id] || ''}
              onChange={e => setDraft(prev => ({ ...prev, [m.user_id]: e.target.value }))}
              style={SELECT}
            >
              <option value="">Nobody</option>
              {members.filter(o => o.user_id !== m.user_id).map(o => (
                <option key={o.user_id} value={o.user_id}>{o.name}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
      {unpaired.length > 0 && (
        <div style={{ fontSize: '11px', color: '#B45309', marginTop: '8px' }}>
          {unpaired.map(m => m.name).join(', ')} {unpaired.length === 1 ? 'has' : 'have'} no reviewer, so their work will not be reviewed.
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '8px' }}>
        <button type="button" onClick={save} disabled={saving || !dirty}
          style={{ padding: '5px 12px', borderRadius: '7px', border: 'none', background: '#16120E', color: '#fff',
                   fontSize: '11px', fontWeight: 600, cursor: saving || !dirty ? 'default' : 'pointer',
                   opacity: saving || !dirty ? 0.5 : 1 }}>
          {saving ? 'Saving…' : 'Save reviewers'}
        </button>
        {msg && <span style={{ fontSize: '11px', color: msg === 'Saved.' ? '#6B6560' : '#C8102E' }}>{msg}</span>}
      </div>
    </div>
  )
}

const OUTCOME_LABEL = {
  happened: 'Checked',
  skipped_unread: 'Answered without reading',
  skipped_no_response: 'Waiting',
  expired: 'Expired',
  duplicated: 'Duplicated',
  reassigned: 'Reassigned',
}

const OUTCOME_COLOR = {
  happened: '#15803D',
  skipped_unread: '#C8102E',
  skipped_no_response: '#6B6560',
  expired: '#9A948E',
  duplicated: '#B45309',
  reassigned: '#9A948E',
}

export function PeerReviewsPanel({ baseUrl, team }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState('')

  const url = `${baseUrl}/${team.id}/reviews`

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await fetch(url, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErr(formatApiErrorDetail(d.detail)); setData(null) }
      else setData(d)
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }, [url])

  useEffect(() => { load() }, [load])

  const reassign = async (assignmentId, reviewerId) => {
    setBusyId(assignmentId); setMsg('')
    try {
      const r = await fetch(`${API_URL}/verification/${assignmentId}/reassign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ reviewer_user_id: reviewerId }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) setMsg(formatApiErrorDetail(d.detail))
      await load()
    } catch {
      setMsg('Network error')
    } finally {
      setBusyId(null)
    }
  }

  if (loading) return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: MUTED }}>Loading peer reviews…</div>
  if (err) return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: '#C8102E' }}>{err}</div>

  const sessions = data?.sessions || []
  if (!sessions.length) return null

  const members = team.members || []
  const nameOf = (uid) => members.find(m => m.user_id === uid)?.name || 'Former member'

  return (
    <div style={{ ...CARD, marginTop: '10px' }}>
      <div style={{ ...SECTION_LABEL, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>Peer reviews</span>
        <button type="button" onClick={load}
          style={{ border: 'none', background: 'none', color: MUTED, fontSize: '11px', cursor: 'pointer', textTransform: 'none', letterSpacing: 0 }}>
          Refresh
        </button>
      </div>
      {msg && <div style={{ fontSize: '12px', color: '#C8102E', marginBottom: '8px' }}>{msg}</div>}
      {sessions.map(s => (
        <div key={s.group_session_id} style={{ marginBottom: '12px' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: '#16120E', marginBottom: '6px' }}>Session {s.session_number}</div>
          <div style={{ display: 'grid', gap: '6px' }}>
            {s.assignments.map(a => {
              // Not after the session ends: the server refuses it, because a
              // reviewer added then could not read or answer anything that counts.
              const pending = s.status !== 'completed'
                && a.status === 'pending' && a.outcome === 'skipped_no_response'
              const options = members.filter(m => m.user_id !== a.author_user_id && m.user_id !== a.reviewer_user_id)
              return (
                <div key={a.assignment_id} data-testid="review-row"
                  style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', fontSize: '12px', color: '#4A4440' }}>
                  <span style={{ fontFamily: 'monospace', color: MUTED }}>{a.section_key}</span>
                  <span>{nameOf(a.author_user_id)} → {nameOf(a.reviewer_user_id)}</span>
                  <span style={{ color: OUTCOME_COLOR[a.outcome] || MUTED, fontWeight: 600 }}>
                    {OUTCOME_LABEL[a.outcome] || a.outcome}
                  </span>
                  {a.routing_policy === 'instructor_reassign' && (
                    <span style={{ fontSize: '11px', color: MUTED }}>(moved by you)</span>
                  )}
                  {pending && options.length > 0 && (
                    <select
                      aria-label={`Reassign review of ${a.section_key}`}
                      value=""
                      disabled={busyId === a.assignment_id}
                      onChange={e => { if (e.target.value) reassign(a.assignment_id, e.target.value) }}
                      style={SELECT}
                    >
                      <option value="">Reassign to…</option>
                      {options.map(o => <option key={o.user_id} value={o.user_id}>{o.name}</option>)}
                    </select>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
