import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import { API_URL, authHeaders, clearSession, readApiError } from '../lib/api'

/** /study-admin: every participant's status, for platform admins in a study
 * build. The condition is hidden until "Show conditions" is ticked (it is not
 * even fetched before that), and no code of any kind is ever shown: the server
 * does not send any. */
export default function StudyAdmin() {
  const user = (() => { try { return JSON.parse(localStorage.getItem('user') || 'null') } catch { return null } })()
  const isAdmin = Boolean(user?.is_platform_admin)
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [showConditions, setShowConditions] = useState(false)
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_URL}/admin/study/status${showConditions ? '?include_conditions=true' : ''}`,
        { headers: { ...authHeaders() } })
      if (!r.ok) {
        setError(r.status === 403 ? 'Platform admins only.' : await readApiError(r, 'Could not load participants'))
        return
      }
      setError('')
      setRows((await r.json()).participants || [])
    } catch {
      setError('Could not reach the server.')
    }
  }, [showConditions])

  useEffect(() => {
    if (!isAdmin) return undefined
    load()
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [load, isAdmin])

  const revoke = async (p) => {
    if (!window.confirm(`Revoke participant ${p.participant_id.slice(0, 8)}? They will be refused from now on. Their data is kept.`)) return
    setBusy(p.participant_id)
    try {
      const r = await fetch(`${API_URL}/admin/study/participants/${p.participant_id}/revoke`,
        { method: 'POST', headers: { ...authHeaders() } })
      if (!r.ok) setError(await readApiError(r, 'Could not revoke'))
    } finally {
      setBusy('')
      load()
    }
  }

  const exportCsv = async () => {
    setBusy('export')
    try {
      const r = await fetch(`${API_URL}/admin/study/export.csv`, { headers: { ...authHeaders() } })
      if (!r.ok) { setError(await readApiError(r, 'Export failed')); return }
      const blob = await r.blob()
      const name = /filename="([^"]+)"/.exec(r.headers.get('content-disposition') || '')?.[1] || 'huskyai-study.csv'
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(a.href)
    } catch {
      setError('Export failed.')
    } finally {
      setBusy('')
    }
  }

  if (!isAdmin) {
    return (
      <Page>
        <p className="text-[14px] text-[#6B6560]">Platform admins only.</p>
      </Page>
    )
  }

  return (
    <Page>
      <CreateParticipants showConditions={showConditions} onCreated={load} />
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <label className="flex items-center gap-2 text-[13px] text-[#4A4440] cursor-pointer select-none">
          <input type="checkbox" checked={showConditions} onChange={e => setShowConditions(e.target.checked)} />
          Show conditions
        </label>
        <button type="button" onClick={load}
          className="px-3 py-[6px] bg-[#FDFCFB] text-[#4A4440] border-[1.5px] border-[#E7E0D8] rounded-[8px] text-[12px] font-semibold cursor-pointer">
          Refresh
        </button>
        <button type="button" onClick={exportCsv} disabled={busy === 'export'}
          className="px-3 py-[6px] bg-[#C8102E] text-white border-none rounded-[8px] text-[12px] font-semibold cursor-pointer disabled:opacity-60">
          {busy === 'export' ? 'Exporting…' : 'Export CSV'}
        </button>
        {rows && <span className="text-[12px] text-[#9A948E]">{rows.length} participant{rows.length === 1 ? '' : 's'}</span>}
      </div>
      {error && <div role="alert" className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[9px] px-3 py-2 mb-3">{error}</div>}
      {rows === null && !error && <p className="text-[13px] text-[#9A948E]">Loading…</p>}
      {rows && (
        <div className="overflow-x-auto bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[12px]">
          <table className="w-full text-[12px] text-[#4A4440] border-collapse">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.5px] text-[#9A948E]">
                <Th>Participant</Th><Th>Response ID</Th><Th>Created</Th><Th>First login</Th><Th>Status</Th>
                {TASKS.map(n => <Th key={n}>Task {n}</Th>)}
                {showConditions && <Th>Condition</Th>}
                {showConditions && <Th>Sets / errors</Th>}
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map(p => (
                <tr key={p.participant_id} data-testid="study-admin-row" className="border-t border-[#E7E0D8]">
                  <Td><span className="font-mono" title={p.participant_id}>{p.participant_id.slice(0, 8)}</span></Td>
                  <Td><span className="font-mono">{p.response_id || '—'}</span></Td>
                  <Td>{fmtTime(p.created_at)}</Td>
                  <Td>{fmtTime(p.first_login_at)}</Td>
                  <Td>{statusLabel(p)}</Td>
                  {p.tasks.map(t => <Td key={t.task}>{taskLabel(t)}</Td>)}
                  {showConditions && <Td>{CONDITION_LABEL[p.condition] || p.condition}</Td>}
                  {showConditions && <Td>{p.set_order ? `set order ${p.set_order}, error order ${p.error_order}` : '—'}</Td>}
                  <Td>
                    {p.status !== 'revoked' && (
                      <button type="button" disabled={busy === p.participant_id} onClick={() => revoke(p)}
                        className="px-2 py-[3px] bg-transparent text-[#C8102E] border-[1.5px] border-[#F9BFCA] rounded-[6px] text-[11px] font-semibold cursor-pointer">
                        Revoke
                      </button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Page>
  )
}

// Lucy's design: HuskyAI (tutor + live feedback) vs standard AI, six tasks.
const CONDITION_LABEL = { feedback: 'HuskyAI', no_feedback: 'standard' }
const TASKS = [1, 2, 3, 4, 5, 6]
const taskLink = (base, n) => `${base}&task=${n}`

/** Mint participant sign-in codes by hand (testing, or a run without the
 * survey's enroll call). Each code takes the next cell of the design
 * (condition, set order, error order), exactly as a survey enrollment does.
 * The server stores only each code's hash, so this result is the one time the
 * codes can be seen: they are kept in this component's state only, never in
 * storage, and are gone on reload. */
function CreateParticipants({ showConditions, onCreated }) {
  const [n, setN] = useState(2)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)

  const valid = Number.isInteger(n) && n >= 1 && n <= 200

  const create = async () => {
    if (!valid || busy) return
    setBusy(true)
    setError('')
    try {
      const r = await fetch(`${API_URL}/admin/study/participants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ n }),
      })
      if (!r.ok) { setError(await readApiError(r, 'Could not create participants')); return }
      setCreated((await r.json()).codes || [])
      onCreated()
    } catch {
      setError('Could not reach the server.')
    } finally {
      setBusy(false)
    }
  }

  const downloadCsv = () => {
    const head = ['participant_id', 'code', 'condition', 'set_order', 'error_order',
      ...TASKS.map(t => `task${t}_link`)]
    const rows = created.map(c => [c.participant_id, c.code, CONDITION_LABEL[c.condition] || c.condition,
      c.set_order ?? '', c.error_order ?? '', ...TASKS.map(t => taskLink(c.link_base, t))])
    const csv = [head, ...rows].map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = `huskyai-study-codes-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="bg-[#FDFCFB] border-[1.5px] border-[#E7E0D8] rounded-[12px] p-5 mb-6">
      <div className="text-[14px] font-semibold text-[#16120E] mb-1">Create participants</div>
      <p className="text-[12px] text-[#6B6560] mb-3 m-0">
        For testing or a run without the survey's enroll call. Survey participants are created automatically by Qualtrics.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[12px] text-[#4A4440]">
          <div className="mb-1 font-semibold">How many</div>
          <input type="number" min={1} max={200} value={Number.isNaN(n) ? '' : n} data-testid="mint-count"
            onChange={e => setN(Number.parseInt(e.target.value, 10))}
            className="w-[90px] px-2 py-[6px] border-[1.5px] border-[#E7E0D8] rounded-[8px] text-[13px]" />
        </label>
        <button type="button" onClick={create} disabled={!valid || busy}
          className="px-4 py-[7px] bg-[#C8102E] text-white border-none rounded-[8px] text-[13px] font-semibold cursor-pointer disabled:opacity-50">
          {busy ? 'Creating…' : 'Create codes'}
        </button>
        <span className="text-[12px] text-[#9A948E]">Conditions and orders are assigned round-robin.</span>
      </div>
      {error && <div role="alert" className="text-[12px] text-red-700 mt-3">{error}</div>}
      {created && (
        <div className="mt-4" data-testid="minted">
          <div className="text-[12px] text-[#C2410C] bg-[#FEF3E8] border border-[#FED7AA] rounded-[8px] px-3 py-2 mb-3">
            Copy or download these now: the codes are shown only once and can't be recovered later.
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px] text-[#4A4440] border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-[0.5px] text-[#9A948E]">
                  <Th>Code</Th>{showConditions && <Th>Condition</Th>}{TASKS.map(t => <Th key={t}>Task {t}</Th>)}
                </tr>
              </thead>
              <tbody>
                {created.map(c => (
                  <tr key={c.participant_id} className="border-t border-[#E7E0D8]">
                    <Td><span className="font-mono text-[13px]">{c.code}</span></Td>
                    {showConditions && <Td>{CONDITION_LABEL[c.condition] || c.condition}</Td>}
                    {TASKS.map(t => (
                      <Td key={t}>
                        <a href={taskLink(c.link_base, t)} target="_blank" rel="noreferrer"
                          className="text-[#C8102E] no-underline">task {t} link</a>
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-2 mt-3">
            <button type="button" onClick={downloadCsv}
              className="px-3 py-[6px] bg-[#FDFCFB] text-[#4A4440] border-[1.5px] border-[#E7E0D8] rounded-[8px] text-[12px] font-semibold cursor-pointer">
              Download codes + links (CSV)
            </button>
            <button type="button" onClick={() => setCreated(null)}
              className="px-3 py-[6px] bg-transparent text-[#9A948E] border-none text-[12px] cursor-pointer">
              Hide
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Page({ children }) {
  const navigate = useNavigate()
  const logout = () => { clearSession(); navigate('/login', { replace: true }) }
  return (
    <div className="flex h-screen bg-[#F7F3EE] overflow-hidden">
      <Sidebar onLogout={logout} />
      <div className="flex-1 flex flex-col overflow-hidden" style={{ marginLeft: 'var(--sidebar-width, 220px)', transition: 'margin-left 200ms ease' }}>
        <div className="h-14 bg-[#FDFCFB] border-b border-[#E7E0D8] flex items-center px-8 flex-shrink-0" style={{ borderBottomWidth: '1.5px' }}>
          <span className="text-[15px] font-semibold text-[#16120E]">Study participants</span>
        </div>
        <div className="flex-1 overflow-y-auto px-8 py-6">
          {children}
        </div>
      </div>
    </div>
  )
}

const Th = ({ children }) => <th className="px-3 py-2 font-bold">{children}</th>
const Td = ({ children }) => <td className="px-3 py-2 align-top whitespace-nowrap">{children}</td>

function fmtTime(iso) {
  if (!iso) return '—'
  // The server stores naive UTC.
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function fmtLeft(seconds) {
  if (seconds == null) return ''
  const m = Math.floor(seconds / 60)
  const s = String(seconds % 60).padStart(2, '0')
  return `${m}:${s}`
}

export function statusLabel(p) {
  switch (p.status) {
    case 'not_used': return 'Not used'
    case 'completed': return 'Completed'
    case 'expired': return 'Expired'
    case 'revoked': return 'Revoked'
    case 'in_progress': {
      const left = p.task_seconds_left != null ? `, ${fmtLeft(p.task_seconds_left)} left` : ''
      return `In progress: task ${p.current_task ?? '?'}${left}`
    }
    default: return p.status
  }
}

function taskLabel(t) {
  if (t.status === 'completed') return `Done (${t.end_reason === 'timer_expired' ? 'timer' : t.end_reason || '—'})`
  if (t.status === 'in_progress') return 'In progress'
  return '—'
}
