import React from 'react'

const classificationColors = {
  Novice: { stroke: '#f87171', text: '#f87171', bg: 'rgba(248,113,113,0.1)' },
  Intermediate: { stroke: '#fbbf24', text: '#fbbf24', bg: 'rgba(251,191,36,0.1)' },
  Advanced: { stroke: '#34d399', text: '#34d399', bg: 'rgba(52,211,153,0.1)' },
}

export default function CircularGauge({ score, classification, leadingStatus, isLoading }) {
  const radius = 70
  const circumference = 2 * Math.PI * radius
  const pct = Math.max(0, Math.min(100, score))
  const offset = circumference - (pct / 100) * circumference

  const colors = classificationColors[classification] || classificationColors.Novice

  return (
    <div className="flex flex-col items-center gap-3">
      {/* SVG Gauge */}
      <div className="relative">
        <svg width="180" height="180" viewBox="0 0 180 180">
          {/* Track */}
          <circle
            cx="90" cy="90" r={radius}
            fill="none"
            stroke="#22222e"
            strokeWidth="10"
          />
          {/* Progress */}
          <circle
            cx="90" cy="90" r={radius}
            fill="none"
            stroke={isLoading ? '#2a2a38' : colors.stroke}
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={isLoading ? circumference : offset}
            transform="rotate(-90 90 90)"
            className="gauge-progress"
            style={{
              filter: isLoading ? 'none' : `drop-shadow(0 0 6px ${colors.stroke}60)`,
            }}
          />
          {/* Glow ring */}
          {!isLoading && pct > 0 && (
            <circle
              cx="90" cy="90" r={radius}
              fill="none"
              stroke={colors.stroke}
              strokeWidth="2"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              transform="rotate(-90 90 90)"
              opacity="0.2"
              className="gauge-progress"
            />
          )}
        </svg>

        {/* Center content */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          {isLoading ? (
            <div className="flex flex-col items-center gap-1">
              <div className="w-8 h-8 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
              <span className="text-xs text-slate-500">Evaluating...</span>
            </div>
          ) : (
            <>
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">PEI Score</span>
              <span
                className="text-4xl font-bold font-mono"
                style={{ color: colors.text }}
              >
                {Math.round(pct)}
              </span>
              <span className="text-xs text-slate-500">/ 100</span>
            </>
          )}
        </div>
      </div>

      {/* Classification & Status badges */}
      {!isLoading && classification && (
        <div className="flex flex-col items-center gap-2">
          <span
            className="px-3 py-1 rounded-full text-sm font-semibold"
            style={{
              color: colors.text,
              backgroundColor: colors.bg,
              border: `1px solid ${colors.stroke}40`,
            }}
          >
            {classification}
          </span>
          <div className="flex items-center gap-2">
            <div className={`w-2 h-2 rounded-full ${
              leadingStatus === 'Leading' ? 'bg-accent-green' : 'bg-accent-red'
            }`} />
            <span className={`text-xs font-medium ${
              leadingStatus === 'Leading' ? 'text-accent-green' : 'text-accent-red'
            }`}>
              {leadingStatus === 'Leading' ? '↑ Leading the LLM' : '↓ Led by the LLM'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
