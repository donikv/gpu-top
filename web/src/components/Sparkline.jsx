// === Sparkline.jsx: a chart from scratch ====================================
// React concepts:
//   * JSX isn't limited to HTML — SVG elements work exactly the same way, so
//     a chart is just a component that maps data to <polyline>/<path> points.
//   * useMemo caches a computed value between renders and recomputes it only
//     when its dependencies change. The dashboard re-renders every 2s poll;
//     without useMemo we'd rebuild these coordinate strings each time even
//     when the history data hasn't changed.
//
// The SVG trick: viewBox="0 0 100 30" defines a virtual 100x30 coordinate
// system that scales to whatever size CSS gives the element — so the math
// below can pretend the chart is always 100 wide.
import { useMemo } from 'react'

const W = 100
const H = 30

export default function Sparkline({ history, field, label, color }) {
  const { points, since, until } = history
  const { line, area, latest } = useMemo(() => {
    const values = points.map((p) => p[field])
    const latest = values.length ? values[values.length - 1] : null
    if (values.length < 2) return { line: '', area: '', latest }

    // X is anchored to the REQUESTED window (since..until), not to the data's
    // own extent — a freshly deployed server honestly shows a short line at
    // the right edge instead of a stretched-to-full-width one.
    const t0 = since
    const span = until - since || 1

    // Fixed 0-100 y-scale: these are percentages, and a stable scale keeps
    // charts comparable across GPUs (auto-scaling makes idle noise look wild).
    const xy = points.map((p) => {
      const x = ((p.ts - t0) / span) * W
      const y = H - (Math.min(100, Math.max(0, p[field] ?? 0)) / 100) * H
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })

    return {
      line: xy.join(' '),
      // Close the polygon down to the baseline for the soft fill under the line.
      area: `${xy.join(' ')} ${xy[xy.length - 1].split(',')[0]},${H} ${xy[0].split(',')[0]},${H}`,
      latest,
    }
  }, [points, field, since, until]) // recompute only when data or window changes

  return (
    <div className="sparkline">
      <div className="sparkline-label">
        <span>{label}</span>
        <span className="sparkline-value" style={{ color }}>
          {latest == null ? '–' : `${latest.toFixed(0)}%`}
        </span>
      </div>
      {/* preserveAspectRatio="none" lets the 100x30 viewBox stretch to fill
          the card instead of keeping its aspect ratio. */}
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="sparkline-svg">
        {/* reference lines at 50% and 100% */}
        <line x1="0" y1={H / 2} x2={W} y2={H / 2} className="gridline" />
        <line x1="0" y1="0.5" x2={W} y2="0.5" className="gridline" />
        {line ? (
          <>
            <polygon points={area} fill={color} opacity="0.15" />
            {/* vector-effect keeps the stroke 1.5px on screen no matter how
                much the viewBox is stretched. */}
            <polyline
              points={line}
              fill="none"
              stroke={color}
              strokeWidth="1.5"
              vectorEffect="non-scaling-stroke"
            />
          </>
        ) : (
          /* fewer than 2 points yet (agent just started): say so instead of
             showing a chart-shaped void */
          <text x={W / 2} y={H / 2} className="sparkline-empty">
            collecting data…
          </text>
        )}
      </svg>
    </div>
  )
}
