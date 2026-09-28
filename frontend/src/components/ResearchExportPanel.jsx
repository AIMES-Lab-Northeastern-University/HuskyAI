import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

/**
 * Download the de-identified research bundle for one of a team's sessions:
 * the event log, the shared document's revisions, per-turn scores, peer-review
 * and contested-answer outcomes, and the turn-taking metrics
 * (backend/research_export.py). Distinct from the admin page's platform-wide
 * conversation export, which knows nothing about the collaborative study.
 *
 * The rule this panel exists to hold: a file that includes students who did
 * not consent must never be mistakable for a consented one. So the filename is
 * built from the downloaded bundle's own `consent_filtered` flag — not from
 * the checkbox — and says INCLUDES-UNCONSENTED when it is false.
 */

const CARD = {
  background: '#FDFCFB',
  borderRadius: '14px',
  border: '1.5px solid #E7E0D8',
  padding: '18px',
}

const MUTED = '#9A948E'

/** Read consent_filtered out of the bundle itself, in either format. */
export function consentFilteredOf(text, fmt) {
  try {
    const head = fmt === 'jsonl' ? text.split('\n', 1)[0] : text
    return JSON.parse(head).consent_filtered === true
  } catch {
    return false  // unknown is treated as NOT consent-filtered: the safe label
  }
}

export function exportFilename({ sessionNumber, fmt, consentFiltered, teamLabel, date = new Date() }) {
  const team = (teamLabel || 'team').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  const day = date.toISOString().slice(0, 10)
  const mode = consentFiltered ? 'consented' : 'INCLUDES-UNCONSENTED'
  return `huskyai-${team}-session${sessionNumber}-${mode}-${day}.${fmt}`
}

function saveText(text, filename, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function ResearchExportPanel({ baseUrl, team, teamLabel }) {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [includeAll, setIncludeAll] = useState(false)
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await fetch(`${baseUrl}/${team.id}/sessions`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) setErr(formatApiErrorDetail(d.detail))
      else setSessions(d.sessions || [])
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }, [baseUrl, team.id])

  useEffect(() => { load() }, [load])

  const download = async (s, fmt) => {
    setBusy(`${s.group_session_id}:${fmt}`); setMsg('')
    try {
      const q = new URLSearchParams({ format: fmt, ...(includeAll ? { include_unconsented: 'true' } : {}) })
      const r = await fetch(`${API_URL}/research/sessions/${s.group_session_id}/export?${q}`,
                            { headers: { ...authHeaders() } })
      const text = await r.text()
      if (!r.ok) {
        let detail = 'Could not download'
        try { detail = formatApiErrorDetail(JSON.parse(text).detail) } catch { /* not JSON */ }
        setMsg(detail)
        return
      }
      const consentFiltered = consentFilteredOf(text, fmt)
      saveText(text, exportFilename({ sessionNumber: s.session_number, fmt, consentFiltered, teamLabel }),
               fmt === 'jsonl' ? 'application/x-ndjson' : 'application/json')
    } catch {
      setMsg('Network error')
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: MUTED }}>Loading sessions…</div>
  if (err) return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: '#C8102E' }}>{err}</div>

  const btn = (disabled) => ({
    padding: '4px 10px', borderRadius: '7px', border: '1.5px solid #E7E0D8', background: '#fff',
    color: '#4A4440', fontSize: '11px', fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.5 : 1,
  })

  return (
    <div style={{ ...CARD, marginTop: '10px' }}>
      <div style={{ fontSize: '11px', fontWeight: 700, color: MUTED, textTransform: 'uppercase', letterSpacing: '0.7px', marginBottom: '6px' }}>
        Research data
      </div>
      <div style={{ fontSize: '12px', color: '#6B6560', lineHeight: 1.6, marginBottom: '10px' }}>
        De-identified bundle for one session: event log, document revisions, scores, peer reviews,
        contested answers and turn-taking. Students appear as pseudonyms.
      </div>

      {sessions.length === 0 ? (
        <div style={{ fontSize: '12px', color: MUTED }}>This team has not started a session yet.</div>
      ) : (
        <div style={{ display: 'grid', gap: '6px' }}>
          {sessions.map(s => (
            <div key={s.group_session_id} data-testid="export-row"
              style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4A4440' }}>
              <span style={{ minWidth: '150px' }}>
                Session {s.session_number} <span style={{ color: MUTED }}>({s.status.replace('_', ' ')})</span>
              </span>
              {['json', 'jsonl'].map(fmt => {
                const b = busy === `${s.group_session_id}:${fmt}`
                return (
                  <button key={fmt} type="button" disabled={Boolean(busy)} onClick={() => download(s, fmt)} style={btn(Boolean(busy))}>
                    {b ? 'Downloading…' : `Download ${fmt.toUpperCase()}`}
                  </button>
                )
              })}
            </div>
          ))}
        </div>
      )}

      <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#4A4440', marginTop: '12px', cursor: 'pointer' }}>
        <input type="checkbox" checked={includeAll} onChange={e => setIncludeAll(e.target.checked)} />
        Include students who did not consent to research
      </label>
      {includeAll && (
        <div role="alert" style={{ fontSize: '11px', color: '#C8102E', lineHeight: 1.6, marginTop: '4px', padding: '6px 8px', background: '#FDE8EC', borderRadius: '6px' }}>
          For reviewing your own section only — <strong>not for research use</strong>. Files are
          named <code>INCLUDES-UNCONSENTED</code> and the bundle records it.
        </div>
      )}
      {msg && <div style={{ fontSize: '12px', color: '#C8102E', marginTop: '8px' }}>{msg}</div>}
    </div>
  )
}
