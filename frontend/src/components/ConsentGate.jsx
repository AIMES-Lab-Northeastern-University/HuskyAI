import { useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

// Blocking research-use notice. Shown to any authenticated user who has not
// acknowledged the notice currently in force (server field
// research_acknowledged === false — the server compares against
// RESEARCH_NOTICE_VERSION, so shipping new wording re-shows this to everyone).
// Accepting turns research consent on (they can still opt out later in
// Settings). Declining is offered only when the server enables it
// (research_notice_allow_decline); it acknowledges the notice with consent off.
//
// A cached acknowledgement renders the app immediately, but is re-checked once
// per load: the cache cannot know that the notice version moved since.
const ACK_KEY = 'research_ack'
// RequireAuth mounts a fresh gate per route, so "once per load" has to live
// outside the component or every navigation would re-fetch.
let verifiedThisLoad = false

export default function ConsentGate({ children }) {
  // 'loading' | 'gate' | 'ok' | 'error'
  const [state, setState] = useState(
    localStorage.getItem(ACK_KEY) === 'true' ? 'ok' : 'loading',
  )
  const [checked, setChecked] = useState(false)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [allowDecline, setAllowDecline] = useState(false)
  // Bumped by "Try again" so the check below actually re-runs.
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (state === 'ok' && verifiedThisLoad) return
    let cancelled = false
    ;(async () => {
      try {
        const r = await fetch(`${API_URL}/auth/me`, { headers: { ...authHeaders() } })
        const d = await r.json().catch(() => ({}))
        if (cancelled) return
        if (r.ok) verifiedThisLoad = true
        if (r.ok && d.research_acknowledged) {
          localStorage.setItem(ACK_KEY, 'true')
          setState('ok')
        } else if (r.ok) {
          localStorage.removeItem(ACK_KEY)
          setAllowDecline(!!d.research_notice_allow_decline)
          setState('gate')
        } else {
          // Not confirmed is not the same as acknowledged. Letting a failed
          // check through meant someone could use the platform, and have their
          // work recorded, without ever seeing the notice. (An expired token
          // is a 401, which the shared fetch handler turns into a login.)
          // A cached acknowledgement stays in the app on a failed re-check
          // (they did see a notice); verifiedThisLoad stays false so the next
          // mount tries again.
          setState((s) => (s === 'ok' ? 'ok' : 'error'))
        }
      } catch {
        if (!cancelled) setState((s) => (s === 'ok' ? 'ok' : 'error'))
      }
    })()
    return () => { cancelled = true }
  }, [attempt])

  const respond = async (accept) => {
    if ((accept && !checked) || saving) return
    setSaving(true)
    setErr('')
    try {
      const r = await fetch(`${API_URL}/auth/me`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(accept ? { accept_research_notice: true }
                                    : { decline_research_notice: true }),
      })
      const d = await r.json().catch(() => ({}))
      if (r.ok) {
        localStorage.setItem(ACK_KEY, 'true')
        setState('ok')
      } else {
        setErr(formatApiErrorDetail(d.detail) || 'Could not save. Try again.')
      }
    } catch {
      setErr('Network error. Try again.')
    } finally {
      setSaving(false)
    }
  }

  if (state === 'loading') {
    return (
      <div className="flex h-screen items-center justify-center bg-[#F7F3EE] text-[#9A948E] text-sm">
        Loading…
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-[#F7F3EE] text-sm text-[#4A4440]">
        <div>We could not reach the server to load your account.</div>
        <button type="button" onClick={() => { setState('loading'); setAttempt((n) => n + 1) }}
                className="px-4 py-2 rounded-[10px] bg-[#C8102E] text-white font-bold cursor-pointer">
          Try again
        </button>
      </div>
    )
  }

  if (state === 'gate') {
    return (
      <div style={{ position: 'fixed', inset: 0, background: 'rgba(22,18,14,0.55)', zIndex: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '24px' }}>
        <div className="bg-[#FDFCFB] rounded-[16px] shadow-xl" style={{ width: '100%', maxWidth: '520px', padding: '32px', border: '1.5px solid #E7E0D8' }}>
          <div style={{ width: '36px', height: '3px', background: '#C8102E', borderRadius: '2px', marginBottom: '18px' }} />
          <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '24px', color: '#16120E', marginBottom: '12px' }}>
            How we use your data
          </div>
          <div style={{ fontSize: '14px', lineHeight: 1.65, color: '#4A4440' }}>
            <p style={{ margin: '0 0 12px' }}>
              HuskyAI is a research project at AIMES Lab, Northeastern University. Your
              conversations and prompt scores help us improve the platform and train models
              that teach better prompting.
            </p>
            <p style={{ margin: '0 0 12px' }}>
              Any data used for research is <strong>anonymized</strong>: your name, email, and
              account id are never included, and personal details in your messages are removed.
            </p>
            <p style={{ margin: 0 }}>
              You can turn research use off anytime in <strong>Settings</strong>. To remove data
              already collected, contact your instructor.
            </p>
          </div>

          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', marginTop: '20px', cursor: 'pointer', fontSize: '14px', color: '#16120E' }}>
            <input
              type="checkbox"
              checked={checked}
              onChange={e => setChecked(e.target.checked)}
              style={{ marginTop: '3px' }}
            />
            <span>I understand and accept how my data is used.</span>
          </label>

          {err && <div style={{ fontSize: '13px', color: '#C8102E', marginTop: '10px' }}>{err}</div>}

          <button
            type="button"
            onClick={() => respond(true)}
            disabled={!checked || saving}
            style={{
              marginTop: '22px', width: '100%', padding: '11px 0', borderRadius: '10px', border: 'none',
              background: !checked || saving ? '#E7E0D8' : '#C8102E',
              color: !checked || saving ? '#9A948E' : '#fff',
              fontSize: '14px', fontWeight: 700,
              cursor: !checked || saving ? 'default' : 'pointer',
            }}
          >
            {saving ? 'Saving…' : 'Continue'}
          </button>
          {allowDecline && (
            <button
              type="button"
              onClick={() => respond(false)}
              disabled={saving}
              style={{
                marginTop: '10px', width: '100%', padding: '10px 0', borderRadius: '10px',
                border: '1.5px solid #E7E0D8', background: 'transparent', color: '#4A4440',
                fontSize: '13px', fontWeight: 600, cursor: saving ? 'default' : 'pointer',
              }}
            >
              Use HuskyAI without taking part
            </button>
          )}
        </div>
      </div>
    )
  }

  return children
}
