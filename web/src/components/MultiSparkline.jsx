// === MultiSparkline.jsx: several series in one small chart ==================
// Same SVG technique as Sparkline.jsx, generalized: `series` is an array of
// { key, color, points } and each becomes its own polyline. Used by the
// cluster view to draw one line per GPU. No area fill here — overlapping
// fills turn to mud with several series.
import { useMemo } from 'react'

const W = 100
const H = 30

export default function MultiSparkline({ series, field, label, since, until }) {
  const lines = useMemo(() => {
    const t0 = since
    const span = until - since || 1
    return series.map((s) => {
      if (s.points.length < 2) return { key: s.key, color: s.color, line: '' }
      const line = s.points
        .map((p) => {
          const x = ((p.ts - t0) / span) * W
          const y = H - (Math.min(100, Math.max(0, p[field] ?? 0)) / 100) * H
          return `${x.toFixed(2)},${y.toFixed(2)}`
        })
        .join(' ')
      return { key: s.key, color: s.color, line }
    })
  }, [series, field, since, until])

  const anyLine = lines.some((l) => l.line)

  return (
    <div className="sparkline">
      <div className="sparkline-label">
        <span>{label}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="sparkline-svg">
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} className="gridline" />
        <line x1="0" y1="0.5" x2={W} y2="0.5" className="gridline" />
        {anyLine ? (
          lines.map((l) =>
            l.line ? (
              <polyline
                key={l.key}
                points={l.line}
                fill="none"
                stroke={l.color}
                strokeWidth="1.2"
                vectorEffect="non-scaling-stroke"
              />
            ) : null,
          )
        ) : (
          <text x={W / 2} y={H / 2} className="sparkline-empty">
            collecting data…
          </text>
        )}
      </svg>
    </div>
  )
}
