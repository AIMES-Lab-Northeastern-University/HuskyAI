import React, { useState } from 'react'
import CircularGauge from './CircularGauge'
import MetricBar from './MetricBar'

const METRICS = ['PSQ', 'CCM', 'TSI', 'CLM', 'RAS']

function Section({ title, icon, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-surface-3 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-surface-2 hover:bg-surface-3 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-base">{icon}</span>
          <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
            {title}
          </span>
        </div>
        <span className="text-slate-500 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="px-3 py-3">{children}</div>}
    </div>
  )
}

function Breakdown({ breakdown }) {
  const items = [
    { label: 'Verb Specificity', value: breakdown.verb_specificity, max: 5, fmt: v => `${v}/5` },
    { label: 'Context Completeness', value: breakdown.context_completeness, max: 100, fmt: v => `${Math.round(v)}%` },
    { label: 'Constraint Defined', value: breakdown.constraint_defined, max: 1, fmt: v => v >= 0.5 ? 'Yes' : 'No' },
    { label: 'Focus Clarity', value: breakdown.focus_clarity, max: 5, fmt: v => `${v}/5` },
    { label: 'Initiative Ratio', value: breakdown.initiative_ratio, max: 1, fmt: v => `${Math.round(v * 100)}%` },
    { label: 'Verification Freq.', value: breakdown.verification_frequency, max: 1, fmt: v => `${Math.round(v * 100)}%` },
    { label: 'Decomposition Depth', value: breakdown.decomposition_depth, max: 10, fmt: v => `${v}/10` },
    { label: 'Chunk Size Score', value: breakdown.chunk_size_appropriate, max: 100, fmt: v => `${Math.round(v)}%` },
    { label: 'Correct Reliance', value: breakdown.correct_reliance_rate, max: 1, fmt: v => `${Math.round(v * 100)}%` },
  ]

  return (
    <div className="space-y-2">
      {items.map(item => {
        const pct = (item.value / item.max) * 100
        const color = pct >= 70 ? '#34d399' : pct >= 40 ? '#fbbf24' : '#f87171'
        return (
          <div key={item.label} className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-36 shrink-0">{item.label}</span>
            <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full metric-bar-fill"
                style={{ width: `${Math.min(100, pct)}%`, backgroundColor: color }}
              />
            </div>
            <span className="text-xs font-mono text-slate-400 w-10 text-right shrink-0">
              {item.fmt(item.value)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function EvalPanel({ evalData, isEvaluating, turnCount }) {
  const hasData = evalData !== null

  const emptyScores = { PSQ: 0, CCM: 0, TSI: 0, CLM: 0, RAS: 0, PEI: 0 }

  return (
    <div className="h-full flex flex-col bg-surface-1 border-l border-surface-3">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-3 shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-accent-purple text-lg">⚡</span>
          <div>
            <h2 className="text-sm font-semibold text-slate-200">Prompt Evaluator</h2>
            <p className="text-xs text-slate-500">Real-time quality analysis</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {turnCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-surface-3 text-slate-400">
              Turn {turnCount}
            </span>
          )}
          {isEvaluating && (
            <div className="flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-accent-blue animate-pulse" />
              <span className="text-xs text-accent-blue">Analyzing</span>
            </div>
          )}
        </div>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">

        {/* Main Gauge */}
        <div className="flex justify-center py-2">
          <CircularGauge
            score={hasData ? evalData.scores.PEI : 0}
            classification={hasData ? evalData.classification : 'Novice'}
            leadingStatus={hasData ? evalData.leading_status : 'Led-by'}
            isLoading={isEvaluating || (!hasData && turnCount === 0)}
          />
        </div>

        {/* Empty state */}
        {!hasData && !isEvaluating && turnCount === 0 && (
          <div className="text-center py-4">
            <p className="text-sm text-slate-500">
              Start a conversation to see your prompt quality analysis
            </p>
            <p className="text-xs text-slate-600 mt-1">
              The evaluator will analyze each turn in real-time
            </p>
          </div>
        )}

        {/* Metrics */}
        <Section title="Dimension Scores" icon="📊" defaultOpen={true}>
          <div className="space-y-3">
            {METRICS.map(m => (
              <MetricBar
                key={m}
                metric={m}
                score={hasData ? evalData.scores[m] : 0}
                isLoading={isEvaluating || (!hasData && turnCount === 0)}
              />
            ))}
          </div>
        </Section>

        {/* Turn Summary */}
        {hasData && evalData.turn_summary && (
          <Section title="Turn Analysis" icon="🔍" defaultOpen={true}>
            <p className="text-xs text-slate-400 leading-relaxed">
              {evalData.turn_summary}
            </p>
          </Section>
        )}

        {/* Suggestions */}
        {hasData && evalData.suggestions?.length > 0 && (
          <Section title="Suggestions" icon="💡" defaultOpen={true}>
            <ul className="space-y-2">
              {evalData.suggestions.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs text-slate-300 leading-relaxed">
                  <span className="text-accent-blue shrink-0 mt-0.5">→</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Strengths */}
        {hasData && evalData.strengths?.length > 0 && (
          <Section title="Strengths" icon="✅" defaultOpen={true}>
            <ul className="space-y-2">
              {evalData.strengths.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs text-accent-green leading-relaxed">
                  <span className="shrink-0 mt-0.5">✓</span>
                  <span>{s}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Red Flags */}
        {hasData && evalData.red_flags?.length > 0 && (
          <Section title="Red Flags" icon="🚨" defaultOpen={true}>
            <ul className="space-y-2">
              {evalData.red_flags.map((f, i) => (
                <li key={i} className="flex gap-2 text-xs text-accent-red leading-relaxed">
                  <span className="shrink-0 mt-0.5">⚠</span>
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {/* Raw Breakdown */}
        {hasData && evalData.breakdown && (
          <Section title="Metric Breakdown" icon="🔬" defaultOpen={false}>
            <Breakdown breakdown={evalData.breakdown} />
          </Section>
        )}

        {/* Formula reference */}
        <div className="rounded-lg border border-surface-3 bg-surface-2 p-3">
          <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">PEI Formula</p>
          <p className="text-xs font-mono text-slate-500 leading-relaxed">
            PEI = 0.25×PSQ + 0.25×CCM<br />
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ 0.20×TSI + 0.15×CLM<br />
            &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;+ 0.15×RAS
          </p>
          <div className="mt-2 flex gap-3 text-xs text-slate-600">
            <span><span className="text-accent-red">■</span> Novice &lt;40</span>
            <span><span className="text-accent-amber">■</span> Intermediate 40-70</span>
            <span><span className="text-accent-green">■</span> Advanced &gt;70</span>
          </div>
        </div>
      </div>
    </div>
  )
}
