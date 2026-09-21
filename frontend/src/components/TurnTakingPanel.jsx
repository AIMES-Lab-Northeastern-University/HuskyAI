import { useCallback, useEffect, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'
import { colorFor } from './ContributionAnalytics'
import InfoIcon from './InfoIcon'

/**
 * Instructor-facing turn-taking, one block per session.
 *
 * Sits below ContributionAnalytics and answers a different question. That panel
 * aggregates across the whole challenge ("who contributed overall"); this one is
 * per session ("how did each session actually unfold"). They are NOT merged:
 * alternation and read-before-write are defined per session, and averaging rates
 * across sessions of different lengths lets a two-turn session outweigh a
 * twenty-turn one.
 *
 * Nothing here is evaluative. These are participation and sequencing measures,
 * not a grade and not an individual skill score -- the same boundary
 * ContributionAnalytics draws, for the same reason.
 *
 * NOTE FOR ANYONE EXTENDING THIS: it must not become student-visible while a
 * study is running. The participation-mirror literature (Conversation Clock,
 * Second Messenger, FairTalk) finds consistently that showing people their own
 * participation changes it -- over-contributors pull back once they see the bar.
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
const UNATTRIBUTED = '#C9C2B8'

/**
 * A missing measure, never a zero.
 *
 * null and 0 are different facts: "there is nothing to measure yet" versus "we
 * measured it and it was none." Rendering a null ratio as 0 would report that a
 * team never reads before writing -- a finding, and a false one, in the
 * direction that looks like a result. So a null gets an em dash and the reason
 * it is missing, and never a drawn bar of any length.
 */
function NoValue({ reason }) {
  return (
    <div>
      <div style={{ fontSize: '20px', color: MUTED, lineHeight: 1.1 }}>—</div>
      <div style={{ fontSize: '11px', color: MUTED, marginTop: '3px' }}>{reason}</div>
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
      <div style={{ fontSize: '11px', color: MUTED, marginTop: '3px' }}>{caption}</div>
    </div>
  )
}

/**
 * The turns in order, one block each, coloured by author.
 *
 * A bare alternation rate cannot distinguish "they went back and forth" from
 * "Ada did six then Sam did six" -- both can land near the same number. The
 * strip shows the runs, which is the thing an instructor actually wants to see.
 * Unattributed turns keep their slot in grey rather than being dropped, so the
 * sequence is not silently closed up.
 */
function SequenceStrip({ sequence, nameById }) {
  if (!sequence?.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px', marginBottom: '10px' }}>
      {sequence.map((uid, i) => {
        const name = uid ? (nameById[uid] || 'Unknown') : null
        return (
          <span
            key={i}
            title={name ? `Turn ${i + 1} · ${name}` : `Turn ${i + 1} · no recorded author`}
            style={{
              width: '10px',
              height: '20px',
              borderRadius: '3px',
              background: name ? colorFor(name) : UNATTRIBUTED,
              flexShrink: 0,
            }}
          />
        )
      })}
    </div>
  )
}

function Legend({ contribution }) {
  if (!contribution?.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 14px' }}>
      {contribution.map(p => (
        <span key={p.user_id} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{
            width: '9px', height: '9px', borderRadius: '2px', background: colorFor(p.name),
          }} />
          <span style={{ fontSize: '11px', color: '#6B6560' }}>
            {p.name} · {p.turns}
          </span>
        </span>
      ))}
    </div>
  )
}

/**
 * Read-before-write as a proportion of writes.
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

function SessionBlock({ s, first }) {
  const nameById = Object.fromEntries((s.contribution || []).map(p => [p.user_id, p.name]))
  const turns = s.conversation_turns || 0
  const rbw = s.read_before_write || {}
  const writes = rbw.writes || 0
  const strict = rbw.other_section || {}

  return (
    <div>
      {!first && <div style={{ height: '1px', background: '#E7E0D8', margin: '18px 0' }} />}

      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '12px' }}>
        <span style={{ fontSize: '13px', fontWeight: 700, color: '#16120E' }}>
          Session {s.session_number}
        </span>
        <span style={{ fontSize: '11px', color: MUTED }}>
          {turns} turn{turns !== 1 ? 's' : ''}
          {s.turns_without_author > 0 && ` · ${s.turns_without_author} unattributed`}
        </span>
        {s.arm && (
          <span style={{
            marginLeft: 'auto', fontSize: '10px', fontWeight: 700, color: '#6B6560',
            background: '#F7F3EE', border: '1px solid #E7E0D8',
            borderRadius: '999px', padding: '2px 8px',
          }}>
            {s.arm}
          </span>
        )}
      </div>

      {turns === 0 ? (
        <div style={{ fontSize: '12px', color: MUTED }}>
          No turns in this session yet.
        </div>
      ) : (
        <>
          <SequenceStrip sequence={s.sequence} nameById={nameById} />
          <Legend contribution={s.contribution} />

          <div style={{ display: 'flex', gap: '28px', flexWrap: 'wrap', marginTop: '16px' }}>
            <div>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Alternation
                <InfoIcon text="How often the speaker changes between consecutive turns. 1.0 means every turn switched speaker; 0 means one person spoke throughout." />
              </div>
              {s.alternation?.conversation == null ? (
                <NoValue reason="Needs at least two attributed turns." />
              ) : (
                <Figure
                  value={s.alternation.conversation.toFixed(2)}
                  caption={`across ${Math.max(0, turns - 1)} consecutive pair${turns - 1 !== 1 ? 's' : ''}`}
                />
              )}
            </div>

            <div style={{ minWidth: '240px' }}>
              <div style={{ ...SECTION_LABEL, marginBottom: '6px' }}>
                Read before write
                <InfoIcon text="Of the section writes in this session, how many came after that student had read a DIFFERENT section — i.e. built on a teammate's work rather than writing in isolation." />
              </div>
              {strict.ratio == null ? (
                <NoValue reason="No sections written yet, so there is nothing to measure." />
              ) : (
                <>
                  <Figure
                    value={strict.ratio.toFixed(2)}
                    caption={`${strict.writes_preceded_by_read} of ${writes} write${writes !== 1 ? 's' : ''} followed a read of a teammate's section`}
                  />
                  <RatioMeter ratio={strict.ratio} />
                  {rbw.any_section?.ratio != null && (
                    <div style={{ fontSize: '11px', color: MUTED, marginTop: '8px' }}>
                      Counting re-reads of the same section:{' '}
                      {rbw.any_section.writes_preceded_by_read} of {writes} ({rbw.any_section.ratio.toFixed(2)})
                    </div>
                  )}
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

  return (
    <div style={{ ...CARD, marginTop: '10px' }}>
      <div style={{ ...SECTION_LABEL, display: 'flex', alignItems: 'center', gap: '6px' }}>
        Turn-taking — session by session
        <InfoIcon text="Participation and sequencing only. These are not quality scores and not an individual skill measure." />
      </div>
      {sessions.map((s, i) => (
        <SessionBlock key={s.group_session_id} s={s} first={i === 0} />
      ))}
    </div>
  )
}
