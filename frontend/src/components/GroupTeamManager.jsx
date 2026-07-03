import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'
import ContributionAnalytics from './ContributionAnalytics'

/**
 * Instructor team builder for a group-mode challenge. Lists teams + members,
 * lets the instructor create teams and assign/remove the section's students.
 * Teams are drawn from the classroom roster — there is no student self-join.
 */
export default function GroupTeamManager({ classroomId, challengeId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [analyticsFor, setAnalyticsFor] = useState(null)

  const base = `${API_URL}/classrooms/${classroomId}/challenges/${challengeId}/teams`

  const load = useCallback(async () => {
    setLoading(true)
    setErr('')
    try {
      const r = await fetch(base, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setErr(formatApiErrorDetail(d.detail))
        setData(null)
      } else {
        setData(d)
      }
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }, [base])

  useEffect(() => { load() }, [load])

  const act = async (fn) => {
    setBusy(true)
    setMsg('')
    try {
      const r = await fn()
      const d = await r.json().catch(() => ({}))
      if (!r.ok) {
        setMsg(formatApiErrorDetail(d.detail))
        return false
      }
      await load()
      return true
    } catch {
      setMsg('Network error')
      return false
    } finally {
      setBusy(false)
    }
  }

  const createTeam = () => act(() =>
    fetch(base, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({}),
    })
  )

  const addMember = (teamId, userId) => act(() =>
    fetch(`${base}/${teamId}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ user_id: userId }),
    })
  )

  const removeMember = (teamId, userId) => act(() =>
    fetch(`${base}/${teamId}/members/${userId}`, { method: 'DELETE', headers: { ...authHeaders() } })
  )

  const deleteTeam = (teamId) => act(() =>
    fetch(`${base}/${teamId}`, { method: 'DELETE', headers: { ...authHeaders() } })
  )

  const btn = {
    padding: '5px 10px',
    borderRadius: '7px',
    border: '1.5px solid #E7E0D8',
    background: 'transparent',
    color: '#4A4440',
    fontSize: '11px',
    fontWeight: 600,
    cursor: busy ? 'default' : 'pointer',
    opacity: busy ? 0.6 : 1,
  }

  if (loading) return <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading teams…</div>
  if (err) return <div style={{ fontSize: '13px', color: '#C8102E' }}>{err}</div>
  if (!data) return null

  const { teams = [], unassigned_students = [], team_min, team_max } = data

  return (
    <div style={{ marginTop: '10px', padding: '12px', background: '#FBF9F6', borderRadius: '9px', border: '1px solid #F0EBE4' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '12px', color: '#6B6560' }}>
          Teams of {team_min}–{team_max}. A team needs at least {team_min} members online to run the challenge.
        </div>
        <button type="button" onClick={createTeam} disabled={busy} style={{ ...btn, background: '#16120E', color: '#fff', borderColor: '#16120E' }}>
          + New team
        </button>
      </div>

      {msg && <div style={{ fontSize: '12px', color: '#C8102E', marginTop: '8px' }}>{msg}</div>}

      {teams.length === 0 ? (
        <div style={{ fontSize: '13px', color: '#9A948E', marginTop: '10px' }}>No teams yet. Create one, then assign students.</div>
      ) : (
        <div style={{ display: 'grid', gap: '10px', marginTop: '10px' }}>
          {teams.map((t, idx) => {
            const full = t.members.length >= (t.max_members ?? team_max)
            return (
              <div key={t.id} style={{ padding: '10px', background: '#fff', borderRadius: '8px', border: '1px solid #F0EBE4' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <div style={{ fontSize: '13px', fontWeight: 600, color: '#16120E' }}>
                    {t.name || `Team ${idx + 1}`}
                    <span style={{ fontSize: '11px', fontWeight: 500, color: t.members.length < team_min ? '#C8102E' : '#9A948E', marginLeft: '8px' }}>
                      {t.members.length}/{t.max_members ?? team_max}
                      {t.members.length < team_min ? ' · needs more' : ''}
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button type="button" onClick={() => setAnalyticsFor(analyticsFor === t.id ? null : t.id)} disabled={busy}
                      style={{ ...btn, ...(analyticsFor === t.id ? { background: '#16120E', color: '#fff', borderColor: '#16120E' } : {}) }}>
                      {analyticsFor === t.id ? 'Hide analytics' : 'Analytics'}
                    </button>
                    <button type="button" onClick={() => deleteTeam(t.id)} disabled={busy} style={{ ...btn, borderColor: '#F9BFCA', color: '#C8102E' }}>
                      Delete team
                    </button>
                  </div>
                </div>

                {t.members.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
                    {t.members.map(m => (
                      <span key={m.user_id} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', color: '#4A4440', background: '#F7F3EE', borderRadius: '20px', padding: '3px 6px 3px 10px' }}>
                        {m.name}
                        <button type="button" aria-label={`Remove ${m.name}`} onClick={() => removeMember(t.id, m.user_id)} disabled={busy}
                          style={{ border: 'none', background: '#E7E0D8', color: '#6B6560', borderRadius: '50%', width: '16px', height: '16px', lineHeight: '14px', fontSize: '11px', cursor: busy ? 'default' : 'pointer' }}>
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}

                <div style={{ marginTop: '8px' }}>
                  <select
                    value=""
                    disabled={busy || full || unassigned_students.length === 0}
                    onChange={e => { if (e.target.value) addMember(t.id, e.target.value) }}
                    style={{ fontSize: '12px', padding: '5px 8px', borderRadius: '7px', border: '1.5px solid #E7E0D8', background: '#fff', color: '#4A4440', maxWidth: '260px' }}
                  >
                    <option value="">
                      {full ? 'Team is full' : unassigned_students.length === 0 ? 'No unassigned students' : '+ Add student…'}
                    </option>
                    {!full && unassigned_students.map(s => (
                      <option key={s.user_id} value={s.user_id}>{s.name} ({s.email})</option>
                    ))}
                  </select>
                </div>

                {analyticsFor === t.id && (
                  <ContributionAnalytics classroomId={classroomId} challengeId={challengeId} teamId={t.id} />
                )}
              </div>
            )
          })}
        </div>
      )}

      {unassigned_students.length > 0 && (
        <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '10px' }}>
          {unassigned_students.length} student{unassigned_students.length !== 1 ? 's' : ''} not yet on a team.
        </div>
      )}
    </div>
  )
}
