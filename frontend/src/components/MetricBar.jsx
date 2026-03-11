import React from 'react'

const metricInfo = {
  PSQ: {
    label: 'Prompt Structural Quality',
    short: 'PSQ',
    description: 'Verb clarity, context, constraints, focus, alignment',
    color: '#C8102E',
  },
  CCM: {
    label: 'Conversation Control',
    short: 'CCM',
    description: 'Initiative ratio, verification, course correction',
    color: '#FF6B8A',
  },
  TSI: {
    label: 'Technical Sophistication',
    short: 'TSI',
    description: 'Decomposition, tool awareness, error anticipation',
    color: '#22d3ee',
  },
  CLM: {
    label: 'Cognitive Load Mgmt',
    short: 'CLM',
    description: 'Chunk size, incremental building, clarification',
    color: '#34d399',
  },
  RAS: {
    label: 'Reliance Appropriateness',
    short: 'RAS',
    description: 'Trust calibration, correct reliance, over/under-reliance',
    color: '#fbbf24',
  },
}

function getScoreColor(score) {
  if (score >= 70) return '#34d399'
  if (score >= 40) return '#fbbf24'
  return '#f87171'
}

export default function MetricBar({ metric, score, isLoading }) {
  const info = metricInfo[metric]
  if (!info) return null

  const displayScore = Math.round(Math.max(0, Math.min(100, score)))
  const pct = displayScore

  return (
    <div className="group">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span
            className="text-xs font-bold font-mono px-1.5 py-0.5 rounded"
            style={{
              color: info.color,
              backgroundColor: `${info.color}15`,
              border: `1px solid ${info.color}30`,
            }}
          >
            {info.short}
          </span>
          <span className="text-xs text-slate-400 group-hover:text-slate-300 transition-colors">
            {info.label}
          </span>
        </div>
        <span
          className="text-sm font-bold font-mono"
          style={{ color: isLoading ? '#2a2a38' : getScoreColor(displayScore) }}
        >
          {isLoading ? '—' : displayScore}
        </span>
      </div>

      {/* Bar */}
      <div className="h-2 bg-surface-3 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full metric-bar-fill"
          style={{
            width: isLoading ? '0%' : `${pct}%`,
            backgroundColor: info.color,
            boxShadow: isLoading ? 'none' : `0 0 8px ${info.color}50`,
          }}
        />
      </div>

      {/* Tooltip-style description on hover */}
      <p className="text-xs text-slate-600 mt-0.5 group-hover:text-slate-500 transition-colors truncate">
        {info.description}
      </p>
    </div>
  )
}
