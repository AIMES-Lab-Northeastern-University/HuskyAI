import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { API_URL, authHeaders, formatApiErrorDetail } from '../lib/api'

// ─── style constants ─────────────────────────────────────────────────────────

const TILE = { borderWidth: '1.5px', borderStyle: 'solid', borderColor: '#E7E0D8' }

const inputStyle = {
  width: '100%',
  padding: '9px 12px',
  borderRadius: '8px',
  border: '1.5px solid #E7E0D8',
  fontSize: '13px',
  background: '#FDFCFB',
  color: '#16120E',
  fontFamily: 'inherit',
  outline: 'none',
  boxSizing: 'border-box',
}

const labelStyle = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  marginBottom: '6px',
  display: 'block',
}

const btnPrimary = {
  padding: '8px 14px',
  borderRadius: '8px',
  border: 'none',
  background: '#C8102E',
  color: '#fff',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
}

const btnPrimaryDisabled = {
  ...btnPrimary,
  background: '#E7E0D8',
  color: '#9A948E',
  cursor: 'not-allowed',
}

const btnSecondary = {
  padding: '8px 14px',
  borderRadius: '8px',
  border: '1.5px solid #E7E0D8',
  background: 'transparent',
  color: '#4A4440',
  fontSize: '13px',
  fontWeight: 600,
  cursor: 'pointer',
}

const SECTION_LABEL = {
  fontSize: '11px',
  fontWeight: 700,
  color: '#9A948E',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  marginBottom: '10px',
}

const EVALUATORS = ['v1', 'v2', 'v3', 'all']
const ALL_VARIANTS = ['v1', 'v2', 'v3']

// ─── helpers ────────────────────────────────────────────────────────────────

function pad2(n) {
  return String(n).padStart(2, '0')
}

function fmtUtc(iso) {
  if (!iso) return '-'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso
    return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())} ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())} UTC`
  } catch { return iso }
}

function fmtDuration(startedAt, endedAt) {
  if (!startedAt || !endedAt) return '-'
  try {
    const s = new Date(startedAt).getTime()
    const e = new Date(endedAt).getTime()
    if (Number.isNaN(s) || Number.isNaN(e)) return '-'
    const ms = Math.max(0, e - s)
    const totalSec = Math.round(ms / 1000)
    const m = Math.floor(totalSec / 60)
    const sec = totalSec % 60
    return `${m}:${pad2(sec)}`
  } catch { return '-' }
}

function num(v, decimals = 1) {
  if (v == null || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(decimals)
}

function pctNum(v, decimals = 1) {
  if (v == null || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  return (n * 100).toFixed(decimals)
}

function signedDelta(v, decimals = 1) {
  if (v == null || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(decimals)}`
}

function deltaBadgeStyle(delta) {
  if (delta == null || Number.isNaN(Number(delta))) {
    return { color: '#9A948E', background: '#F7F3EE' }
  }
  const abs = Math.abs(Number(delta))
  if (abs <= 5) return { color: '#15803D', background: '#DCFCE7' }
  if (abs <= 15) return { color: '#D97706', background: '#FEF9EC' }
  return { color: '#C8102E', background: '#FDE8EC' }
}

// ─── small components ───────────────────────────────────────────────────────

function StatTile({ label, value }) {
  return (
    <div className="bg-[#FDFCFB] rounded-[14px]" style={{ ...TILE, padding: '14px' }}>
      <div style={{ fontSize: '10px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '26px', color: '#16120E', marginTop: '4px', lineHeight: 1.1 }}>{value}</div>
    </div>
  )
}

function DeltaBadge({ delta }) {
  const s = deltaBadgeStyle(delta)
  return (
    <span style={{
      fontSize: '12px',
      fontWeight: 700,
      padding: '2px 8px',
      borderRadius: '20px',
      background: s.background,
      color: s.color,
      display: 'inline-block',
      minWidth: '46px',
      textAlign: 'center',
    }}>
      {signedDelta(delta)}
    </span>
  )
}

// ─── chart helpers ──────────────────────────────────────────────────────────

const COLOR = {
  green: '#15803D',
  greenBg: '#DCFCE7',
  amber: '#D97706',
  amberBg: '#FEF9EC',
  red: '#C8102E',
  redBg: '#FDE8EC',
  grey: '#9A948E',
  ink: '#16120E',
  border: '#E7E0D8',
  gold: '#F97316',
}

// Distinct palette for the per-variant overlay charts. Picked for high contrast
// on a light background while still feeling coordinated.
const GOLDEN_COLOR = '#0F172A'   // slate-900
const VARIANT_COLOR = {
  v1: '#EF4444',  // red-500
  v2: '#06B6D4',  // cyan-500
  v3: '#A855F7',  // purple-500
}
const VARIANT_BG = {
  v1: '#FEE2E2',
  v2: '#CFFAFE',
  v3: '#F3E8FF',
}

function stddevColor(v) {
  if (v == null || Number.isNaN(Number(v))) return COLOR.grey
  const a = Math.abs(Number(v))
  if (a <= 3) return COLOR.green
  if (a <= 10) return COLOR.amber
  return COLOR.red
}

function variantList(reportsByVariant) {
  return ['v1', 'v2', 'v3'].filter(v => reportsByVariant && reportsByVariant[v])
}

/** Cases line chart — 20 cases on x (sorted by golden ascending), one line for
 *  the golden score plus one overlaid line per available variant. The headline
 *  chart for spotting where each evaluator agrees / drifts. */
function CasesLineChart({ reportsByVariant }) {
  const variants = variantList(reportsByVariant)
  if (variants.length === 0) return null
  const base = reportsByVariant[variants[0]].cases || []
  const sorted = base
    .map(c => ({ id: c.id, domain: c.domain, tier: c.tier, golden: c?.golden?.PEI }))
    .filter(c => c.golden != null)
    .sort((a, b) => a.golden - b.golden)
  if (sorted.length === 0) return null

  const lineFor = (v) => {
    const byId = new Map((reportsByVariant[v].cases || []).map(c => [c.id, c]))
    return sorted.map(s => byId.get(s.id)?.aggregate?.predicted_pei_mean ?? null)
  }
  const goldenY = sorted.map(s => s.golden)
  const variantY = Object.fromEntries(variants.map(v => [v, lineFor(v)]))

  const N = sorted.length
  const W = 820, H = 360
  const padL = 50, padR = 18, padT = 18, padB = 64
  const innerW = W - padL - padR, innerH = H - padT - padB
  const xScale = i => padL + (i / Math.max(N - 1, 1)) * innerW
  const yScale = v => padT + innerH - (v / 100) * innerH

  const buildPath = (values) => {
    const out = []
    let started = false
    values.forEach((v, i) => {
      if (v == null) { started = false; return }
      out.push(`${started ? 'L' : 'M'} ${xScale(i).toFixed(1)} ${yScale(v).toFixed(1)}`)
      started = true
    })
    return out.join(' ')
  }

  const tickEvery = N <= 12 ? 1 : Math.ceil(N / 10)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
      {[0, 25, 50, 75, 100].map(t => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={yScale(t)} y2={yScale(t)} stroke="#E5E7EB" strokeWidth="1" />
          <text x={padL - 6} y={yScale(t) + 3} fontSize="10" fill="#94A3B8" textAnchor="end">{t}</text>
        </g>
      ))}
      {/* golden first (thicker, on top of variants only conceptually — actually drawn behind) */}
      <path d={buildPath(goldenY)} fill="none" stroke={GOLDEN_COLOR} strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" opacity="0.95" />
      {variants.map(v => (
        <path key={v} d={buildPath(variantY[v])} fill="none" stroke={VARIANT_COLOR[v]} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" opacity="0.9" />
      ))}
      {/* dots */}
      {sorted.map((s, i) => (
        <g key={s.id}>
          <circle cx={xScale(i)} cy={yScale(goldenY[i])} r="3.5" fill={GOLDEN_COLOR}>
            <title>{`${s.id} (${s.domain}) — golden ${goldenY[i].toFixed(0)}`}</title>
          </circle>
          {variants.map(v => variantY[v][i] != null && (
            <circle key={v} cx={xScale(i)} cy={yScale(variantY[v][i])} r="3.5" fill={VARIANT_COLOR[v]} stroke="#FDFCFB" strokeWidth="1.2" opacity="0.95">
              <title>{`${s.id} — ${v}: ${variantY[v][i].toFixed(1)} (golden ${goldenY[i].toFixed(0)}, error ${(variantY[v][i] - goldenY[i]).toFixed(1)})`}</title>
            </circle>
          ))}
        </g>
      ))}
      {/* x-axis labels */}
      {sorted.map((s, i) => (i % tickEvery === 0) && (
        <text
          key={s.id} x={xScale(i)} y={padT + innerH + 14}
          fontSize="9" fill="#64748B" textAnchor="end"
          transform={`rotate(-50 ${xScale(i)} ${padT + innerH + 14})`}
        >{s.id}</text>
      ))}
      <text x={padL + innerW / 2} y={H - 8} fontSize="11" fill="#475569" textAnchor="middle" fontWeight="600">
        Benchmark cases (sorted by golden score ascending)
      </text>
      <text x={14} y={padT + innerH / 2} fontSize="11" fill="#475569" textAnchor="middle" fontWeight="600"
            transform={`rotate(-90 14 ${padT + innerH / 2})`}>
        PEI score
      </text>
      {/* legend (top-left, inside plot) */}
      <g transform={`translate(${padL + 10}, ${padT + 6})`}>
        <rect x="-6" y="-6" width="98" height={(variants.length + 1) * 18 + 8} fill="#FFFFFF" opacity="0.92" rx="6" stroke="#E5E7EB" strokeWidth="1" />
        <g transform="translate(0,0)">
          <line x1="0" x2="18" y1="7" y2="7" stroke={GOLDEN_COLOR} strokeWidth="3" strokeLinecap="round" />
          <circle cx="9" cy="7" r="3.5" fill={GOLDEN_COLOR} />
          <text x="26" y="10" fontSize="11" fontWeight="700" fill="#0F172A">Golden</text>
        </g>
        {variants.map((v, i) => (
          <g key={v} transform={`translate(0, ${(i + 1) * 18})`}>
            <line x1="0" x2="18" y1="7" y2="7" stroke={VARIANT_COLOR[v]} strokeWidth="3" strokeLinecap="round" />
            <circle cx="9" cy="7" r="3.5" fill={VARIANT_COLOR[v]} />
            <text x="26" y="10" fontSize="11" fontWeight="700" fill="#0F172A">{v}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}

/** Overall percentage error per variant — single grouped bar per evaluator. */
function OverallErrorBars({ reportsByVariant }) {
  const variants = variantList(reportsByVariant)
  if (variants.length === 0) return null
  const data = variants.map(v => ({
    variant: v,
    error: Number(reportsByVariant[v].summary?.pei_mae) || 0,
    classAcc: Number(reportsByVariant[v].summary?.classification_accuracy) || 0,
  }))
  const peak = Math.max(20, ...data.map(d => d.error))

  const W = 480, H = 240
  const padL = 50, padR = 18, padT = 24, padB = 42
  const innerW = W - padL - padR, innerH = H - padT - padB
  const slot = innerW / Math.max(data.length, 1)
  const barW = slot * 0.5

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
      {[0, peak / 2, peak].map(t => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={padT + innerH - (t / peak) * innerH} y2={padT + innerH - (t / peak) * innerH} stroke="#E5E7EB" strokeWidth="1" />
          <text x={padL - 6} y={padT + innerH - (t / peak) * innerH + 3} fontSize="10" fill="#94A3B8" textAnchor="end">{t.toFixed(0)}%</text>
        </g>
      ))}
      {data.map((d, i) => {
        const x = padL + i * slot + (slot - barW) / 2
        const h = (d.error / peak) * innerH
        const y = padT + innerH - h
        return (
          <g key={d.variant}>
            <rect x={x} y={y} width={barW} height={Math.max(h, 1)} fill={VARIANT_COLOR[d.variant]} rx="6" />
            <text x={x + barW / 2} y={Math.max(y - 8, padT + 14)} fontSize="14" fontWeight="800" fill="#0F172A" textAnchor="middle">
              {d.error.toFixed(1)}%
            </text>
            <text x={x + barW / 2} y={padT + innerH + 22} fontSize="13" fontWeight="700" fill="#1F2937" textAnchor="middle">
              {d.variant}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

/** Per-domain grouped bars — one group per domain, one bar per variant. */
function DomainErrorBars({ reportsByVariant }) {
  const variants = variantList(reportsByVariant)
  if (variants.length === 0) return null
  // Gather the union of domains seen in any variant's by_domain map.
  const domains = Array.from(new Set(
    variants.flatMap(v => Object.keys(reportsByVariant[v].summary?.by_domain || {})),
  ))
  if (domains.length === 0) return null
  const matrix = domains.map(d => ({
    domain: d,
    values: variants.map(v => ({
      variant: v,
      error: Number(reportsByVariant[v].summary?.by_domain?.[d]?.pei_mae) || 0,
    })),
  }))
  const peak = Math.max(20, ...matrix.flatMap(m => m.values.map(x => x.error)))

  const W = 720, H = 260
  const padL = 50, padR = 18, padT = 22, padB = 56
  const innerW = W - padL - padR, innerH = H - padT - padB
  const slot = innerW / domains.length
  const groupInner = slot * 0.78
  const barW = groupInner / variants.length * 0.85
  const gap = (groupInner - barW * variants.length) / Math.max(variants.length - 1, 1)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
      {[0, peak / 2, peak].map(t => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={padT + innerH - (t / peak) * innerH} y2={padT + innerH - (t / peak) * innerH} stroke="#E5E7EB" strokeWidth="1" />
          <text x={padL - 6} y={padT + innerH - (t / peak) * innerH + 3} fontSize="10" fill="#94A3B8" textAnchor="end">{t.toFixed(0)}</text>
        </g>
      ))}
      {matrix.map((m, gi) => {
        const groupStart = padL + gi * slot + (slot - groupInner) / 2
        return (
          <g key={m.domain}>
            {m.values.map((v, bi) => {
              const x = groupStart + bi * (barW + gap)
              const h = (v.error / peak) * innerH
              const y = padT + innerH - h
              return (
                <g key={v.variant}>
                  <rect x={x} y={y} width={barW} height={Math.max(h, 1)} fill={VARIANT_COLOR[v.variant]} rx="3" />
                  <text x={x + barW / 2} y={Math.max(y - 4, padT + 10)} fontSize="10" fontWeight="700" fill="#0F172A" textAnchor="middle">
                    {v.error.toFixed(1)}
                  </text>
                </g>
              )
            })}
            <text x={padL + gi * slot + slot / 2} y={padT + innerH + 18} fontSize="12" fontWeight="700" fill="#1F2937" textAnchor="middle">
              {m.domain}
            </text>
          </g>
        )
      })}
      {/* legend */}
      <g transform={`translate(${padL}, ${H - 8})`}>
        {variants.map((v, i) => (
          <g key={v} transform={`translate(${i * 64}, 0)`}>
            <rect x="0" y="-8" width="12" height="12" fill={VARIANT_COLOR[v]} rx="3" />
            <text x="18" y="2" fontSize="11" fontWeight="700" fill="#1F2937">{v}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}

/** Per-dimension grouped bars — one group per PEI sub-dimension, one bar per variant. */
function DimensionErrorBars({ reportsByVariant }) {
  const variants = variantList(reportsByVariant)
  if (variants.length === 0) return null
  const dims = [
    { key: 'psq_mae', label: 'PSQ' },
    { key: 'ccm_mae', label: 'CCM' },
    { key: 'tsi_mae', label: 'TSI' },
    { key: 'clm_mae', label: 'CLM' },
    { key: 'ras_mae', label: 'RAS' },
  ]
  const matrix = dims.map(d => ({
    label: d.label,
    values: variants.map(v => ({
      variant: v,
      error: Number(reportsByVariant[v].summary?.[d.key]) || 0,
    })),
  }))
  const peak = Math.max(20, ...matrix.flatMap(m => m.values.map(x => x.error)))

  const W = 720, H = 260
  const padL = 50, padR = 18, padT = 22, padB = 56
  const innerW = W - padL - padR, innerH = H - padT - padB
  const slot = innerW / dims.length
  const groupInner = slot * 0.78
  const barW = groupInner / variants.length * 0.85
  const gap = (groupInner - barW * variants.length) / Math.max(variants.length - 1, 1)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
      {[0, peak / 2, peak].map(t => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={padT + innerH - (t / peak) * innerH} y2={padT + innerH - (t / peak) * innerH} stroke="#E5E7EB" strokeWidth="1" />
          <text x={padL - 6} y={padT + innerH - (t / peak) * innerH + 3} fontSize="10" fill="#94A3B8" textAnchor="end">{t.toFixed(0)}</text>
        </g>
      ))}
      {matrix.map((m, gi) => {
        const groupStart = padL + gi * slot + (slot - groupInner) / 2
        return (
          <g key={m.label}>
            {m.values.map((v, bi) => {
              const x = groupStart + bi * (barW + gap)
              const h = (v.error / peak) * innerH
              const y = padT + innerH - h
              return (
                <g key={v.variant}>
                  <rect x={x} y={y} width={barW} height={Math.max(h, 1)} fill={VARIANT_COLOR[v.variant]} rx="3" />
                  <text x={x + barW / 2} y={Math.max(y - 4, padT + 10)} fontSize="10" fontWeight="700" fill="#0F172A" textAnchor="middle">
                    {v.error.toFixed(1)}
                  </text>
                </g>
              )
            })}
            <text x={padL + gi * slot + slot / 2} y={padT + innerH + 18} fontSize="12" fontWeight="700" fill="#1F2937" textAnchor="middle">
              {m.label}
            </text>
          </g>
        )
      })}
      <g transform={`translate(${padL}, ${H - 8})`}>
        {variants.map((v, i) => (
          <g key={v} transform={`translate(${i * 64}, 0)`}>
            <rect x="0" y="-8" width="12" height="12" fill={VARIANT_COLOR[v]} rx="3" />
            <text x="18" y="2" fontSize="11" fontWeight="700" fill="#1F2937">{v}</text>
          </g>
        ))}
      </g>
    </svg>
  )
}

/** Stability box plot — one box per case, sorted by stddev descending.
 *  Box = min..max PEI across runs, median line, orange dot for golden PEI. */
function StabilityBoxPlot({ cases }) {
  const rows = (cases || []).map(c => {
    const peis = (c.runs || []).map(r => r?.predicted?.PEI).filter(v => v != null && !Number.isNaN(Number(v))).map(Number)
    if (peis.length < 2) return null
    const sorted = [...peis].sort((a, b) => a - b)
    const min = sorted[0]
    const max = sorted[sorted.length - 1]
    const median = sorted[Math.floor(sorted.length / 2)]
    return {
      id: c.id,
      domain: c.domain,
      min, max, median,
      golden: c?.golden?.PEI,
      stddev: Number(c?.aggregate?.predicted_pei_stddev) || 0,
    }
  }).filter(Boolean)
  if (rows.length === 0) return null
  rows.sort((a, b) => (b.stddev || 0) - (a.stddev || 0))

  const W = Math.max(540, 30 + rows.length * 28), H = 220
  const padL = 36, padR = 12, padT = 8, padB = 58
  const innerW = W - padL - padR, innerH = H - padT - padB
  const colW = innerW / rows.length
  const boxW = Math.min(18, colW * 0.55)
  const yScale = v => padT + innerH - (v / 100) * innerH

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
      {[0, 25, 50, 75, 100].map(t => (
        <g key={t}>
          <line x1={padL} x2={W - padR} y1={yScale(t)} y2={yScale(t)} stroke="#F0EBE5" strokeWidth="1" />
          <text x={padL - 6} y={yScale(t) + 3} fontSize="10" fill={COLOR.grey} textAnchor="end">{t}</text>
        </g>
      ))}
      {rows.map((r, i) => {
        const cx = padL + i * colW + colW / 2
        const x = cx - boxW / 2
        const y = yScale(r.max)
        const h = Math.max(yScale(r.min) - yScale(r.max), 1)
        const c = stddevColor(r.stddev)
        return (
          <g key={r.id}>
            <rect x={x} y={y} width={boxW} height={h} fill={c} opacity="0.22" rx="2" />
            <line x1={x} x2={x + boxW} y1={yScale(r.median)} y2={yScale(r.median)} stroke={c} strokeWidth="2" />
            {r.golden != null && <circle cx={cx} cy={yScale(r.golden)} r="3" fill={COLOR.gold} />}
            <text
              x={cx} y={padT + innerH + 12}
              fontSize="9" fill="#6B6560" textAnchor="end"
              transform={`rotate(-50 ${cx} ${padT + innerH + 12})`}
            >{r.id}</text>
          </g>
        )
      })}
      <g transform={`translate(${padL}, ${H - 8})`}>
        <circle cx="4" cy="0" r="3" fill={COLOR.gold} />
        <text x="14" y="3" fontSize="10" fill="#4A4440">golden PEI</text>
        <rect x="100" y="-5" width="10" height="10" fill={COLOR.green} opacity="0.22" />
        <text x="116" y="3" fontSize="10" fill="#4A4440">stable</text>
        <rect x="170" y="-5" width="10" height="10" fill={COLOR.amber} opacity="0.22" />
        <text x="186" y="3" fontSize="10" fill="#4A4440">mixed</text>
        <rect x="240" y="-5" width="10" height="10" fill={COLOR.red} opacity="0.22" />
        <text x="256" y="3" fontSize="10" fill="#4A4440">unstable</text>
      </g>
    </svg>
  )
}

// ─── main component ─────────────────────────────────────────────────────────

export default function AdminBenchmark() {
  const [evaluator, setEvaluator] = useState('v1')
  const [repeats, setRepeats] = useState(3)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState('')
  const [runProgress, setRunProgress] = useState('')        // high-level (e.g. "Running v1 (1/3)…")
  const [streamProgress, setStreamProgress] = useState(null) // per-stream detail object
  const [lastAllRunSummary, setLastAllRunSummary] = useState(null)
  const [allReports, setAllReports] = useState(null)         // { v1: report, v2: report, v3: report } from last "All" run

  const [reports, setReports] = useState([])
  const [reportsLoading, setReportsLoading] = useState(false)
  const [reportsErr, setReportsErr] = useState('')

  const [selectedReportId, setSelectedReportId] = useState('')
  const [currentReport, setCurrentReport] = useState(null)
  const [reportLoading, setReportLoading] = useState(false)
  const [reportErr, setReportErr] = useState('')

  const [expandedCaseId, setExpandedCaseId] = useState(null)

  // ─── load reports list ───────────────────────────────────────────────────
  const loadReports = useCallback(async () => {
    setReportsErr('')
    setReportsLoading(true)
    try {
      const r = await fetch(`${API_URL}/admin/benchmark/reports`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => [])
      if (r.ok) {
        const list = Array.isArray(d) ? d : []
        setReports(list)
        return list
      } else {
        setReportsErr(formatApiErrorDetail(d.detail) || 'Could not load reports')
        return []
      }
    } catch {
      setReportsErr('Network error loading reports')
      return []
    } finally {
      setReportsLoading(false)
    }
  }, [])

  const loadReportById = useCallback(async (reportId) => {
    if (!reportId) return
    setReportErr('')
    setReportLoading(true)
    setExpandedCaseId(null)
    try {
      const r = await fetch(`${API_URL}/admin/benchmark/reports/${reportId}`, { headers: { ...authHeaders() } })
      const d = await r.json().catch(() => ({}))
      if (r.ok) {
        setCurrentReport(d)
      } else {
        setReportErr(formatApiErrorDetail(d.detail) || 'Could not load report')
      }
    } catch {
      setReportErr('Network error loading report')
    } finally {
      setReportLoading(false)
    }
  }, [])

  // initial load — fetch list, auto-select latest, and load the latest report of
  // each variant (v1/v2/v3) so the combined comparison charts render from disk
  // without needing a fresh "All" run.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const list = await loadReports()
      if (cancelled) return

      // Latest-per-variant: list is newest-first, so first occurrence wins.
      const latestIds = {}
      for (const r of list) {
        if (r?.evaluator && !latestIds[r.evaluator]) latestIds[r.evaluator] = r.report_id
      }
      const wanted = ['v1', 'v2', 'v3'].filter(v => latestIds[v])
      if (wanted.length > 0) {
        try {
          const results = await Promise.all(wanted.map(v =>
            fetch(`${API_URL}/admin/benchmark/reports/${latestIds[v]}`, { headers: { ...authHeaders() } })
              .then(r => r.ok ? r.json() : null)
              .catch(() => null)
          ))
          if (!cancelled) {
            const map = {}
            wanted.forEach((v, i) => { if (results[i]) map[v] = results[i] })
            if (Object.keys(map).length > 0) setAllReports(map)
          }
        } catch {
          // non-fatal: combined charts simply won't render
        }
      }

      if (list.length > 0) {
        const first = list[0]
        setSelectedReportId(first.report_id)
        await loadReportById(first.report_id)
      }
    })()
    return () => { cancelled = true }
  }, [loadReports, loadReportById])

  // ─── run a new benchmark ─────────────────────────────────────────────────
  // Helper: stream a single evaluator run via NDJSON. Updates streamProgress as
  // each (case, repeat) finishes. Returns { ok, report, report_id, error }.
  const runOneVariant = useCallback(async (variant, reps) => {
    setStreamProgress({ variant, completed: 0, total: 0, current: '', failed: 0, latestPei: null, elapsed: 0 })
    try {
      const r = await fetch(`${API_URL}/admin/benchmark/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ evaluator: variant, repeats: reps }),
      })
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        return { ok: false, error: formatApiErrorDetail(d.detail) || `HTTP ${r.status}` }
      }
      if (!r.body) {
        return { ok: false, error: 'Streaming not supported by this browser/proxy' }
      }

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalReport = null
      let finalReportId = null
      let streamError = null

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (value) {
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''
          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed) continue
            let event
            try { event = JSON.parse(trimmed) } catch { continue }
            if (event.type === 'started') {
              setStreamProgress({
                variant,
                completed: 0,
                total: Number(event.total_runs) || 0,
                current: '',
                failed: 0,
                latestPei: null,
                elapsed: 0,
              })
            } else if (event.type === 'progress') {
              setStreamProgress({
                variant,
                completed: Number(event.completed) || 0,
                total: Number(event.total) || 0,
                current: event.case_id || '',
                failed: Number(event.failed_so_far) || 0,
                latestPei: event.predicted_pei == null ? null : Number(event.predicted_pei),
                elapsed: Number(event.elapsed_seconds) || 0,
              })
            } else if (event.type === 'done') {
              finalReport = event.report
              finalReportId = event.report_id
            } else if (event.type === 'error') {
              streamError = event.error || 'Benchmark stream error'
            }
          }
        }
        if (done) break
      }

      if (streamError) return { ok: false, error: streamError }
      if (!finalReport) return { ok: false, error: 'Stream ended without a final report' }
      return { ok: true, report: finalReport, report_id: finalReportId }
    } catch {
      return { ok: false, error: 'Network error during streaming run' }
    }
  }, [])

  const runBenchmark = useCallback(async () => {
    if (running) return
    setRunError('')
    setRunning(true)
    setLastAllRunSummary(null)
    setAllReports(null)
    const reps = Number(repeats) || 1

    try {
      if (evaluator === 'all') {
        const collected = []
        const reportsByVariant = {}
        for (let i = 0; i < ALL_VARIANTS.length; i++) {
          const v = ALL_VARIANTS[i]
          setRunProgress(`Running ${v} (${i + 1}/${ALL_VARIANTS.length})…`)
          const res = await runOneVariant(v, reps)
          if (!res.ok) {
            // Record the failure but continue with the next variant.
            collected.push({ evaluator: v, error: res.error })
            continue
          }
          if (res.report) reportsByVariant[v] = res.report
          collected.push({
            evaluator: v,
            report_id: res.report_id,
            pei_mae: res?.report?.summary?.pei_mae ?? null,
            classification_accuracy: res?.report?.summary?.classification_accuracy ?? null,
            mean_pei_stddev: res?.report?.summary?.mean_pei_stddev ?? null,
          })
          // Display the most recently completed report so user sees progress
          if (res.report) {
            setCurrentReport(res.report)
            setExpandedCaseId(null)
          }
          if (res.report_id) setSelectedReportId(res.report_id)
        }
        setLastAllRunSummary(collected)
        setAllReports(Object.keys(reportsByVariant).length > 0 ? reportsByVariant : null)
        const failedCount = collected.filter(x => x.error).length
        if (failedCount > 0 && failedCount === ALL_VARIANTS.length) {
          setRunError('All three variants failed - see browser network tab for details.')
        }
        await loadReports()
      } else {
        setRunProgress(`Running ${evaluator}…`)
        const res = await runOneVariant(evaluator, reps)
        if (res.ok) {
          if (res.report) {
            setCurrentReport(res.report)
            setExpandedCaseId(null)
          }
          if (res.report_id) setSelectedReportId(res.report_id)
          await loadReports()
        } else {
          setRunError(res.error)
        }
      }
    } finally {
      setRunning(false)
      setRunProgress('')
      setStreamProgress(null)
    }
  }, [evaluator, repeats, running, loadReports, runOneVariant])

  // ─── select report from dropdown ─────────────────────────────────────────
  const onSelectReport = useCallback((id) => {
    setSelectedReportId(id)
    if (id) loadReportById(id)
  }, [loadReportById])

  // ─── report options ──────────────────────────────────────────────────────
  const reportOptions = useMemo(() => {
    return reports.map(r => {
      const mae = r?.summary?.pei_mae
      const maeText = mae == null ? '—' : Number(mae).toFixed(1)
      const label = `${r.evaluator} · r${r.repeats} · ${fmtUtc(r.started_at)} · error ${maeText}`
      return { id: r.report_id, label }
    })
  }, [reports])

  const summary = currentReport?.summary || {}
  const cases = currentReport?.cases || []
  const byDomain = summary?.by_domain || {}
  const domainRows = useMemo(() => Object.entries(byDomain).map(([k, v]) => ({ domain: k, ...v })), [byDomain])

  // Mean signed bias (predicted - golden) across all cases that have both values.
  // Positive = evaluator runs generous; negative = evaluator runs harsh.
  const meanSignedBias = useMemo(() => {
    const deltas = cases.map(c => {
      const g = c?.golden?.PEI
      const p = c?.aggregate?.predicted_pei_mean
      if (g == null || p == null) return null
      return Number(p) - Number(g)
    }).filter(v => v != null && !Number.isNaN(v))
    if (deltas.length === 0) return null
    return deltas.reduce((a, b) => a + b, 0) / deltas.length
  }, [cases])

  // ─── render ──────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1280px' }}>

      {/* ── Run panel ── */}
      <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={TILE}>
        <div style={SECTION_LABEL}>Run benchmark</div>

        <div style={{ display: 'flex', gap: '24px', alignItems: 'flex-end', flexWrap: 'wrap' }}>

          {/* evaluator pill */}
          <div>
            <label style={labelStyle}>Evaluator</label>
            <div style={{ display: 'inline-flex', background: '#F7F3EE', padding: '3px', borderRadius: '8px', border: '1px solid #E7E0D8' }}>
              {EVALUATORS.map(opt => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => setEvaluator(opt)}
                  disabled={running}
                  style={{
                    padding: '5px 16px',
                    borderRadius: '6px',
                    fontSize: '13px',
                    fontWeight: 600,
                    border: 'none',
                    cursor: running ? 'not-allowed' : 'pointer',
                    background: evaluator === opt ? '#16120E' : 'transparent',
                    color: evaluator === opt ? '#fff' : '#6B6560',
                    fontFamily: 'inherit',
                  }}
                >
                  {opt === 'all' ? 'All' : opt}
                </button>
              ))}
            </div>
          </div>

          {/* repeats */}
          <div style={{ width: '180px' }}>
            <label style={labelStyle}>Repeats</label>
            <input
              type="number"
              min={1}
              max={10}
              value={repeats}
              onChange={e => {
                const v = parseInt(e.target.value, 10)
                if (Number.isNaN(v)) setRepeats('')
                else setRepeats(Math.max(1, Math.min(10, v)))
              }}
              disabled={running}
              style={inputStyle}
            />
            <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '4px', lineHeight: 1.55 }}>
              Higher = better stableness signal but expensive.
            </div>
          </div>

          {/* run button */}
          <div>
            <button
              type="button"
              onClick={runBenchmark}
              disabled={running}
              style={running ? btnPrimaryDisabled : btnPrimary}
            >
              {running ? 'Running…' : 'Run benchmark'}
            </button>
          </div>
        </div>

        <div style={{ fontSize: '11px', color: '#9A948E', marginTop: '14px', lineHeight: 1.55 }}>
          Takes ~2-10 minutes per variant depending on evaluator and repeats. <strong>All</strong> runs v1, v2, v3 sequentially (3× as long). v3 is the most expensive.
          {' '}If you hit OpenAI rate limits, set <code style={{ fontSize: '11px' }}>BENCHMARK_CONCURRENCY=1</code> and{' '}
          <code style={{ fontSize: '11px' }}>BENCHMARK_PACE_SECONDS=2</code> in <code style={{ fontSize: '11px' }}>backend/.env</code> and restart.
        </div>

        {running && (
          <div style={{ marginTop: '12px' }}>
            <div style={{ fontSize: '12px', color: '#15803D', fontWeight: 600, marginBottom: '6px' }}>
              {runProgress || 'Run in progress.'} Don't close the tab.
            </div>
            {streamProgress && streamProgress.total > 0 && (
              <div style={{
                background: '#F7F3EE',
                border: '1.5px solid #E7E0D8',
                borderRadius: '10px',
                padding: '12px 14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px', gap: '12px', flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'baseline', fontSize: '13px', color: '#16120E', fontWeight: 600 }}>
                    <span style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      color: '#C8102E',
                      background: '#FDE8EC',
                      padding: '2px 8px',
                      borderRadius: '20px',
                      letterSpacing: '0.04em',
                    }}>{streamProgress.variant}</span>
                    <span style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', lineHeight: 1 }}>
                      {streamProgress.completed}<span style={{ color: '#9A948E' }}>/{streamProgress.total}</span>
                    </span>
                    <span style={{ fontSize: '12px', color: '#6B6560', fontWeight: 500 }}>
                      runs
                    </span>
                  </div>
                  <div style={{ display: 'flex', gap: '14px', fontSize: '12px', color: '#6B6560' }}>
                    <span><strong style={{ color: '#16120E' }}>{Math.round(streamProgress.elapsed)}s</strong> elapsed</span>
                    {streamProgress.completed > 0 && streamProgress.total > 0 && (
                      <span>
                        <strong style={{ color: '#16120E' }}>
                          ~{Math.max(0, Math.round((streamProgress.elapsed / streamProgress.completed) * (streamProgress.total - streamProgress.completed)))}s
                        </strong> remaining
                      </span>
                    )}
                    {streamProgress.failed > 0 && (
                      <span style={{ color: '#C8102E', fontWeight: 600 }}>{streamProgress.failed} errors</span>
                    )}
                  </div>
                </div>

                {/* progress bar */}
                <div style={{ height: '6px', background: '#E7E0D8', borderRadius: '999px', overflow: 'hidden', marginBottom: '8px' }}>
                  <div style={{
                    height: '100%',
                    background: '#C8102E',
                    borderRadius: '999px',
                    width: `${Math.round((streamProgress.completed / streamProgress.total) * 100)}%`,
                    transition: 'width 0.25s ease',
                  }} />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '11px', color: '#9A948E', gap: '10px', flexWrap: 'wrap' }}>
                  <span>
                    Current case: <strong style={{ color: '#4A4440', fontFamily: 'ui-monospace, "SF Mono", Menlo, monospace' }}>
                      {streamProgress.current || '…'}
                    </strong>
                  </span>
                  {streamProgress.latestPei != null && (
                    <span>
                      last PEI: <strong style={{ color: '#16120E' }}>{Number(streamProgress.latestPei).toFixed(1)}</strong>
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {runError && (
          <div style={{
            marginTop: '12px',
            padding: '9px 12px',
            borderRadius: '8px',
            background: '#FDE8EC',
            color: '#C8102E',
            fontSize: '13px',
            fontWeight: 600,
            border: '1px solid #F9BFCA',
          }}>
            {runError}
          </div>
        )}

        {lastAllRunSummary && lastAllRunSummary.length > 0 && (
          <div style={{
            marginTop: '14px',
            padding: '12px 14px',
            borderRadius: '10px',
            background: '#F7F3EE',
            border: '1.5px solid #E7E0D8',
          }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
              Last All-run comparison
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '10px' }}>
              {lastAllRunSummary.map(row => (
                <div
                  key={row.evaluator}
                  style={{
                    background: '#FDFCFB',
                    border: '1.5px solid #E7E0D8',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    cursor: row.report_id ? 'pointer' : 'default',
                  }}
                  onClick={() => row.report_id && onSelectReport(row.report_id)}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                    <span style={{
                      fontSize: '11px',
                      fontWeight: 700,
                      color: '#C8102E',
                      background: '#FDE8EC',
                      padding: '2px 8px',
                      borderRadius: '20px',
                      letterSpacing: '0.04em',
                    }}>{row.evaluator}</span>
                    {row.error
                      ? <span style={{ fontSize: '11px', fontWeight: 700, color: '#C8102E' }}>failed</span>
                      : <span style={{ fontSize: '11px', color: '#9A948E' }}>click to view</span>
                    }
                  </div>
                  {row.error ? (
                    <div style={{ fontSize: '11px', color: '#C8102E', lineHeight: 1.5, marginTop: '2px' }}>
                      {row.error}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'baseline', flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ fontSize: '10px', color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.04em' }}>PEI Error</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E', lineHeight: 1 }}>
                          {row.pei_mae == null ? '—' : Number(row.pei_mae).toFixed(1)}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Class. Accuracy</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E', lineHeight: 1 }}>
                          {row.classification_accuracy == null ? '—' : `${Math.round(Number(row.classification_accuracy) * 100)}%`}
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '10px', color: '#9A948E', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Std. Dev.</div>
                        <div style={{ fontFamily: "'Instrument Serif', serif", fontSize: '20px', color: '#16120E', lineHeight: 1 }}>
                          {row.mean_pei_stddev == null ? '—' : Number(row.mean_pei_stddev).toFixed(1)}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Prior reports selector ── */}
      <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={TILE}>
        <div style={SECTION_LABEL}>Previous reports</div>

        {reportsErr && (
          <div style={{ fontSize: '13px', color: '#C8102E', marginBottom: '10px' }}>{reportsErr}</div>
        )}

        {reportsLoading && reports.length === 0 ? (
          <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading reports…</div>
        ) : reports.length === 0 ? (
          <div style={{ fontSize: '13px', color: '#6B6560' }}>
            No reports yet. Run one above to get started.
          </div>
        ) : (
          <div style={{ maxWidth: '640px' }}>
            <select
              value={selectedReportId}
              onChange={e => onSelectReport(e.target.value)}
              style={{ ...inputStyle, cursor: 'pointer' }}
            >
              {reportOptions.map(o => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* ── Report viewer ── */}
      {reportLoading && (
        <div style={{ fontSize: '13px', color: '#9A948E' }}>Loading report…</div>
      )}

      {reportErr && !reportLoading && (
        <div style={{
          padding: '12px 14px',
          borderRadius: '10px',
          background: '#FDE8EC',
          color: '#C8102E',
          fontSize: '13px',
          fontWeight: 600,
          border: '1px solid #F9BFCA',
        }}>
          {reportErr}
        </div>
      )}

      {currentReport && !reportLoading && (
        <>
          {/* header strip */}
          <div className="bg-[#FDFCFB] rounded-[14px] p-5" style={TILE}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', fontSize: '13px', color: '#4A4440' }}>
              <span style={{
                fontSize: '12px',
                fontWeight: 700,
                padding: '3px 10px',
                borderRadius: '20px',
                background: '#FDE8EC',
                color: '#C8102E',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}>
                {currentReport.evaluator}
              </span>
              <span style={{ color: '#9A948E' }}>·</span>
              <span>repeats={currentReport.repeats}</span>
              <span style={{ color: '#9A948E' }}>·</span>
              <span>{currentReport.case_count} cases</span>
              <span style={{ color: '#9A948E' }}>·</span>
              <span>started {fmtUtc(currentReport.started_at)}</span>
              <span style={{ color: '#9A948E' }}>·</span>
              <span>duration {fmtDuration(currentReport.started_at, currentReport.ended_at)}</span>
            </div>
          </div>

          {/* Headline tiles — the 5 numbers that matter most. */}
          <div>
            <div style={SECTION_LABEL}>At a glance</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: '10px', maxWidth: '900px' }}>
              <StatTile label="Mean Absolute Error (PEI)" value={num(summary.pei_mae)} />
              <StatTile label="Mean Signed Bias" value={meanSignedBias == null ? '—' : signedDelta(meanSignedBias, 1)} />
              <StatTile label="Classification Accuracy" value={summary.classification_accuracy == null ? '—' : `${pctNum(summary.classification_accuracy)}%`} />
              <StatTile label="Mean Standard Deviation" value={num(summary.mean_pei_stddev)} />
              <StatTile label="Max Standard Deviation" value={num(summary.max_pei_stddev)} />
            </div>
            <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '6px', lineHeight: 1.55, maxWidth: '900px' }}>
              Mean Absolute Error: average distance from golden. Mean Signed Bias: positive = evaluator runs generous, negative = harsh. Standard Deviation: spread of predicted PEI across repeats (lower = more reliable).
            </div>
          </div>

          {/* Combined comparison charts — driven by the latest report per variant on disk.
              Auto-populates from the reports list on mount. The single source of comparison. */}
          {allReports && variantList(allReports).length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={SECTION_LABEL}>
                Comparing latest {variantList(allReports).join(' / ')} report{variantList(allReports).length === 1 ? '' : 's'}
              </div>

              {/* 1. Cases line chart — 20 cases × golden + variant predictions. */}
              <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A', marginBottom: '10px' }}>
                  Predicted vs golden score per case
                </div>
                <CasesLineChart reportsByVariant={allReports} />
                <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '6px', lineHeight: 1.5 }}>
                  Each marker is one of the 20 benchmark cases. The dark line is the golden score; coloured lines are the predictions from each variant. Cases are sorted by golden score ascending so the dark line rises smoothly and you can see where each variant pulls away from it.
                </div>
              </div>

              {/* 2 + 3. Overall + domain side-by-side. */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
                <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A', marginBottom: '10px' }}>
                    Overall percentage error from golden
                  </div>
                  <OverallErrorBars reportsByVariant={allReports} />
                  <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '4px', lineHeight: 1.5 }}>
                    Mean Absolute Error of PEI across all 20 cases. Lower bar = closer to the golden judge.
                  </div>
                </div>
                <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A', marginBottom: '10px' }}>
                    Error by domain
                  </div>
                  <DomainErrorBars reportsByVariant={allReports} />
                  <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '4px', lineHeight: 1.5 }}>
                    Per-domain Mean Absolute Error. Reveals whether a variant is weak on a specific kind of task.
                  </div>
                </div>
              </div>

              {/* 4. Per-dimension grouped bars. */}
              <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A', marginBottom: '10px' }}>
                  Error by PEI dimension
                </div>
                <DimensionErrorBars reportsByVariant={allReports} />
                <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '4px', lineHeight: 1.5 }}>
                  Mean Absolute Error per scoring dimension (PSQ, CCM, TSI, CLM, RAS). A tall bar in one dimension = the variant struggles to score that dimension reliably.
                </div>
              </div>
            </div>
          )}

          {/* Stability box plot — drill-down on the currently selected single report. Only meaningful with repeats > 1. */}
          {(currentReport.repeats || 0) > 1 && (
            <div className="bg-[#FDFCFB] rounded-[14px] p-4" style={TILE}>
              <div style={{ fontSize: '13px', fontWeight: 700, color: '#0F172A', marginBottom: '4px' }}>
                Stability across repeats — {currentReport.evaluator}
              </div>
              <div style={{ fontSize: '11px', color: COLOR.grey, marginBottom: '10px' }}>
                For the currently selected report ({currentReport.report_id}).
              </div>
              <StabilityBoxPlot cases={cases} />
              <div style={{ fontSize: '11px', color: COLOR.grey, marginTop: '4px', lineHeight: 1.5 }}>
                Each box = predicted PEI range across the {currentReport.repeats} repeats for that case. Orange dot is the golden PEI. Sorted by instability — leftmost cases drift the most across runs.
              </div>
            </div>
          )}

          {/* per-case table */}
          {cases.length > 0 && (
            <div>
              <div style={SECTION_LABEL}>Per case</div>
              <div className="bg-[#FDFCFB] rounded-[14px] overflow-hidden" style={TILE}>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                    <thead>
                      <tr style={{ background: '#F7F3EE', textAlign: 'left', color: '#6B6560' }}>
                        <th style={{ padding: '9px 14px', fontWeight: 700 }}>ID</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700 }}>Domain</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700 }}>Tier</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Golden PEI</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Predicted PEI (mean)</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Δ</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Standard Deviation</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Classification Match</th>
                        <th style={{ padding: '9px 14px', fontWeight: 700, textAlign: 'center' }}>Runs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cases.map(c => {
                        const isOpen = expandedCaseId === c.id
                        const agg = c.aggregate || {}
                        const goldenPei = c?.golden?.PEI
                        const runs = Array.isArray(c.runs) ? c.runs : []
                        const totalRepeats = currentReport.repeats ?? runs.length
                        return (
                          <Fragment key={c.id}>
                            <tr
                              onClick={() => setExpandedCaseId(isOpen ? null : c.id)}
                              style={{
                                borderTop: '1px solid #F0EBE5',
                                cursor: 'pointer',
                                background: isOpen ? '#FAFAF8' : 'transparent',
                              }}
                              onMouseEnter={e => { if (!isOpen) e.currentTarget.style.background = '#FAFAF8' }}
                              onMouseLeave={e => { if (!isOpen) e.currentTarget.style.background = '' }}
                            >
                              <td style={{ padding: '9px 14px', fontFamily: 'monospace', fontSize: '12px', color: '#16120E' }}>{c.id}</td>
                              <td style={{ padding: '9px 14px', color: '#4A4440' }}>{c.domain ?? '—'}</td>
                              <td style={{ padding: '9px 14px', color: '#4A4440' }}>{c.tier ?? '—'}</td>
                              <td style={{ padding: '9px 14px', textAlign: 'center', color: '#4A4440' }}>{goldenPei == null ? '—' : num(goldenPei, 0)}</td>
                              <td style={{ padding: '9px 14px', textAlign: 'center', color: '#16120E', fontWeight: 600 }}>{num(agg.predicted_pei_mean)}</td>
                              <td style={{ padding: '9px 14px', textAlign: 'center' }}><DeltaBadge delta={agg.pei_delta} /></td>
                              <td style={{ padding: '9px 14px', textAlign: 'center', color: '#4A4440' }}>{num(agg.predicted_pei_stddev)}</td>
                              <td style={{ padding: '9px 14px', textAlign: 'center' }}>
                                {(() => {
                                  const rate = agg.classification_match_rate
                                  if (rate == null) return <span style={{ color: '#9A948E' }}>—</span>
                                  const n = Number(rate)
                                  if (n === 1.0) return <span style={{ color: '#15803D', fontWeight: 700 }}>✓</span>
                                  if (n === 0.0) return <span style={{ color: '#C8102E', fontWeight: 700 }}>✗</span>
                                  const matched = Math.round(n * (agg.successful_runs || runs.length || 1))
                                  const denom = agg.successful_runs || runs.length || 1
                                  return <span style={{ color: '#D97706', fontWeight: 600, fontSize: '12px' }}>{matched}/{denom}</span>
                                })()}
                              </td>
                              <td style={{ padding: '9px 14px', textAlign: 'center', color: '#9A948E', fontSize: '12px' }}>
                                {(agg.successful_runs ?? runs.length)}/{totalRepeats}
                              </td>
                            </tr>
                            {isOpen && (
                              <tr style={{ background: '#FAFAF8' }}>
                                <td colSpan={9} style={{ padding: '12px 18px', borderTop: '1px solid #F0EBE5' }}>
                                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                    {runs.length === 0 && (
                                      <div style={{ fontSize: '12px', color: '#9A948E' }}>No run data.</div>
                                    )}
                                    {runs.map((run, idx) => {
                                      const k = run.run_index ?? idx
                                      if (run.error) {
                                        return (
                                          <div key={k} style={{ fontSize: '12px', color: '#C8102E', fontFamily: 'monospace' }}>
                                            Run {k}: ERROR {String(run.error)}
                                          </div>
                                        )
                                      }
                                      const predPei = run?.predicted?.PEI
                                      const goldP = c?.golden?.PEI
                                      const d = (predPei != null && goldP != null) ? (Number(predPei) - Number(goldP)) : null
                                      const cls = run?.predicted?.classification ?? '—'
                                      const lead = run?.predicted?.leading_status ?? '—'
                                      const lat = run?.latency_ms
                                      return (
                                        <div key={k} style={{ fontSize: '12px', color: '#4A4440', fontFamily: 'monospace' }}>
                                          Run {k}: PEI {num(predPei)} (Δ {signedDelta(d)}), classification {cls}, leading_status {lead}, latency {lat == null ? '—' : `${lat}ms`}
                                        </div>
                                      )
                                    })}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
