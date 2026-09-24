import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'
import { colorFor } from './ContributionAnalytics'
import InfoIcon from './InfoIcon'

/**
 * Instructor-facing turn-taking, one block per session.
 *
 * Reads the metrics computed by backend/analysis/turn_taking.py — the same pure
 * function behind /research/sessions/{id}/turn-taking — through the
 * classroom-scoped team route. Definitions live in docs/metrics-codebook.md and
 * are versioned; the version in force is shown at the foot of the panel so a
 * number an instructor screenshots stays traceable.
 *
 * Sits below ContributionAnalytics and answers a different question. That panel
 * aggregates prompt share across the whole challenge ("who talked to the coach
 * overall"); this one is per session and about the shared artifact ("how did
 * this session actually unfold"). They are NOT merged: alternation and
 * read-before-write are defined per session, and averaging rates across
 * sessions of different lengths lets a two-turn session outweigh a twenty-turn
 * one.
 *
 * Nothing here is evaluative. These are participation and sequencing measures,
 * not a grade and not an individual skill score.
 *
 * NOTE FOR ANYONE EXTENDING THIS: it must not become student-visible while a
 * study is running. The participation-mirror literature (Conversation Clock,
 * Second Messenger, FairTalk) finds consistently that showing people their own
 * participation changes it — over-contributors pull back once they see the bar.
 * That is a feature in a facilitation tool and a contaminant in a measurement,
 * because the thing being altered is the thing being measured.
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

const MUTED = '#9A948E'

/**
 * A missing measure, never a zero.
 *
 * null and 0 are different facts: "there is nothing to measure yet" versus "we
 * measured it and it was none." Several values from the metrics module are
 * deliberately null, and rendering one as 0 would report that a team never
 * reads before writing — a finding, and a false one, in the direction that
 * looks like a result. So a null gets an em dash and the reason it is missing,
 * and never a drawn bar of any length.
 */
function NoValue({ reason }) {
  return (
    <div>
      <div style={{ fontSize: '20px', color: MUTED, lineHeight: 1.1 }}>—</div>
      <div style={{ fontSize: '11px', color: MUTED, marginTop: '3px', maxWidth: '240px' }}>{reason}</div>
    </div>
  )
}

function Figure({ value, caption }) {
  return (
    <div>
      <div style={{
        fontFamily: '"JetBrains Mono", monospace',
        fontSize: '20px',
        fontWeight: 700,
        color: '#16120E',
        lineHeight: 1.1,
      }}>
        {value}
      </div>
      <div style={{ fontSize: '11px', color: MUTED, marginTop: '3px', maxWidth: '240px' }}>{caption}</div>
    </div>
  )
}

/**
 * A proportion, as a bar.
 *
 * The fill is body ink, deliberately not a status colour. Whether a high ratio
 * is "good" is the research question, not something the UI gets to assert by
 * painting it green.
 */
function RatioMeter({ ratio }) {
  const pct = Math.max(0, Math.min(1, ratio)) * 100
  return (
    <div style={{
      height: '8px',
      background: '#F7F3EE',
      border: '1px solid #E7E0D8',
      borderRadius: '999px',
      overflow: 'hidden',
      marginTop: '8px',
      maxWidth: '260px',
    }}>
      <div style={{
        height: '100%',
        width: `${pct}%`,
        background: '#4A4440',
        borderRadius: '999px',
        transition: 'width 0.5s ease',
      }} />
    </div>
  )
}

/** Contribution share of the shared artifact, per member. */
function Shares({ s, nameById }) {
  const uids = Object.keys(s.contribution_share || {})
  if (!uids.length) return null
  const rows = uids
    .map(uid => ({
      uid,
      name: nameById[uid] || 'Unknown',
      writes: (s.writes_by_user || {})[uid] || 0,
      share: (s.contribution_share || {})[uid] || 0,
    }))
    .sort((a, b) => b.writes - a.writes)

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 16px' }}>
      {rows.map(r => (
        <span key={r.uid} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{
            width: '9px', height: '9px', borderRadius: '2px', background: colorFor(r.name),
          }} />
          <span style={{ fontSize: '11px', color: '#6B6560' }}>
            {r.name} · {r.writes} write{r.writes !== 1 ? 's' : ''}
            {s.totals?.artifact_writes ? ` (${Math.round(r.share * 100)}%)` : ''}
          </span>
        </span>
      ))}
    </div>
  )
}

function latencyText(ms) {
  if (ms == null) return null
  if (ms < 1000) return `${ms} ms`
  const secs = ms / 1000
  if (secs < 90) return `${secs.toFixed(secs < 10 ? 1 : 0)} s`
  return `${Math.round(secs / 60)} min`
}

function SessionBlock({ s, nameById, first }) {
  const writes = s.totals?.artifact_writes || 0
  const rbw = s.read_before_write || {}
  const reliance = s.coach_reliance || {}
  const equality = s.equality || {}

  return (
    <div>
      {!first && <div style={{ height: '1px', background: '#E7E0D8', margin: '18px 0' }} />}

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '12px' }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>
          Session {s.session_number}
        </span>
        <span style={{ fontSize: '11px', color: MUTED }}>
          {writes} write{writes !== 1 ? 's' : ''}
          {' · '}{s.totals?.coach_turns || 0} coach turn{(s.totals?.coach_turns || 0) !== 1 ? 's' : ''}
          {' · '}{s.totals?.human_reads || 0} read{(s.totals?.human_reads || 0) !== 1 ? 's' : ''}
        </span>
        {s.status && (
          <span style={{
            marginLeft: 'auto', fontSize: '10px', fontWeight: 700, color: '#6B6560',
            background: '#F7F3EE', border: '1px solid #E7E0D8',
            borderRadius: '999px', padding: '2px 8px',
          }}>
            {s.status.replace(/_/g, ' ')}
          </span>
        )}
      </div>

      {writes === 0 && !(s.totals?.coach_turns) ? (
        <div style={{ fontSize: '12px', color: MUTED }}>Nothing recorded in this session yet.</div>
      ) : (
        <>
          <Shares s={s} nameById={nameById} />

          <div style={{ display: 'flex', gap: '28px', flexWrap: 'wrap', marginTop: '16px' }}>
            <div>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Alternation
                <InfoIcon text="How often the artifact changed hands between consecutive writes. 1.0 means every write came from a different member than the one before it; 0 means one member wrote a whole block uninterrupted." />
              </div>
              {s.alternation_rate == null ? (
                <NoValue reason="Needs at least two writes — one write has no pair to compare." />
              ) : (
                <Figure
                  value={s.alternation_rate.toFixed(2)}
                  caption={`across ${Math.max(0, writes - 1)} consecutive pair${writes - 1 !== 1 ? 's' : ''}`}
                />
              )}
            </div>

            <div style={{ minWidth: '250px' }}>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Read before write
                <InfoIcon text="Of the writes made when a teammate's section already existed, how many came after that student had actually expanded a teammate-authored section. Writes made when there was nothing of a teammate's to read are excluded from the denominator, not counted as failures." />
              </div>
              {rbw.ratio == null ? (
                <NoValue reason="No write yet had a teammate's section available to read." />
              ) : (
                <>
                  <Figure
                    value={rbw.ratio.toFixed(2)}
                    caption={`${rbw.informed_writes} of ${rbw.eligible_writes} eligible write${rbw.eligible_writes !== 1 ? 's' : ''} followed a read of a teammate's section`}
                  />
                  <RatioMeter ratio={rbw.ratio} />
                </>
              )}
            </div>

            <div>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Equality
                <InfoIcon text="Gini: 0 is a perfectly even split of writes, approaching 1 is one member doing everything. Normalised entropy: 1.0 is every member contributing equally, 0 is a single member contributing everything. Both are reported because they disagree usefully — entropy is more sensitive to how many members participated at all." />
              </div>
              {equality.gini == null ? (
                <NoValue reason="No writes yet, so there is no distribution to measure." />
              ) : (
                <Figure
                  value={equality.gini.toFixed(2)}
                  caption={equality.normalised_entropy == null
                    ? 'Gini'
                    : `Gini · entropy ${equality.normalised_entropy.toFixed(2)}`}
                />
              )}
            </div>

            <div>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Write → read
                <InfoIcon text="Median time from a section write to the first time a DIFFERENT member expanded that same section. Contributions nobody else opened are counted separately rather than folded into the median." />
              </div>
              {s.median_write_to_read_ms == null ? (
                <NoValue reason="No contribution has been read by a teammate yet." />
              ) : (
                <Figure
                  value={latencyText(s.median_write_to_read_ms)}
                  caption={`median · ${s.writes_never_read_by_a_teammate} never read by a teammate`}
                />
              )}
            </div>

            <div style={{ minWidth: '230px' }}>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Coach reliance
                <InfoIcon text="Among writes made when a teammate's work was available to adopt: coach-copied text versus text the student typed after reading a teammate. Both are adoption; the question is adoption of whose work." />
              </div>
              {reliance.ratio == null ? (
                <NoValue reason="No coach-copied or teammate-informed write yet." />
              ) : (
                <>
                  <Figure
                    value={reliance.ratio.toFixed(2)}
                    caption={`${reliance.coach_copied_eligible_writes} coach-copied vs ${reliance.teammate_informed_writes} teammate-informed`}
                  />
                  <RatioMeter ratio={reliance.ratio} />
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

export default function TurnTakingPanel({ classroomId, challengeId, teamId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  const url = `${API_URL}/classrooms/${classroomId}/challenges/${challengeId}/teams/${teamId}/turn-taking`

  const load = useCallback(async () => {
    setLoading(true)
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

  if (loading) {
    return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: MUTED }}>Loading turn-taking…</div>
  }
  if (err) {
    return <div style={{ ...CARD, marginTop: '10px', fontSize: '13px', color: '#C8102E' }}>{err}</div>
  }

  const sessions = data?.sessions || []
  if (!sessions.length) return null

  const nameById = data?.member_names || {}
  const version = sessions[0]?.metrics_version

  return (
    <div style={{ ...CARD, marginTop: '10px' }}>
      <div style={{ ...SECTION_LABEL, display: 'flex', alignItems: 'center', gap: '6px' }}>
        Turn-taking — session by session
        <InfoIcon text="Participation and sequencing only, derived from the event log rather than anything self-reported. These are not quality scores and not an individual skill measure." />
      </div>
      {sessions.map((s, i) => (
        <SessionBlock key={s.group_session_id} s={s} nameById={nameById} first={i === 0} />
      ))}
      {version && (
        <div style={{ fontSize: '10px', color: MUTED, marginTop: '16px' }}>
          Definitions: docs/metrics-codebook.md · metrics version {version}
        </div>
      )}
    </div>
  )
}
