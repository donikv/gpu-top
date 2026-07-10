// === GpuCard.jsx: one GPU's live numbers + history charts ===================
// React concepts:
//   * props are read-only inputs; all interactivity that belongs to THIS card
//     (the selected time window) is local state with useState.
//   * state is per component INSTANCE: every GpuCard has its own `minutes`,
//     which is why each card can show a different window at the same time.
import { useState } from 'react'
import { useHistory } from '../hooks/useHistory'
import Gauge from './Gauge'
import Sparkline from './Sparkline'

// Plain data + tiny helpers can live next to the component. Not everything
// needs to be React.
const WINDOWS = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
]

const fmt = (v, suffix = '') => (v == null ? '–' : `${Math.round(v)}${suffix}`)

export default function GpuCard({ serverName, gpu }) {
  const [minutes, setMinutes] = useState(60)

  // Hooks compose: this custom hook re-fetches whenever the window changes,
  // because `minutes` is in its dependency array.
  const points = useHistory(serverName, gpu.gpu_index, minutes)

  const memPct =
    gpu.mem_total_mib > 0 ? (gpu.mem_used_mib / gpu.mem_total_mib) * 100 : null

  return (
    <div className="gpu-card">
      <div className="gpu-card-title">
        <span className="gpu-index">GPU {gpu.gpu_index}</span>
        <span className="gpu-name">{gpu.gpu_name}</span>
      </div>

      <div className="gauges">
        <Gauge label="util" value={gpu.util_pct} />
        <Gauge label="mem" value={memPct} />
      </div>

      <div className="gpu-stats">
        <span>{fmt(gpu.temp_c, '°C')}</span>
        <span>
          {fmt(gpu.power_w, '')}/{fmt(gpu.power_limit_w, ' W')}
        </span>
        {/* JSX conditional: passive GPUs report no fan (null) — skip it. */}
        {gpu.fan_pct != null && <span>fan {fmt(gpu.fan_pct, '%')}</span>}
        <span>
          {fmt(gpu.mem_used_mib)}/{fmt(gpu.mem_total_mib)} MiB
        </span>
      </div>

      <div className="window-picker">
        {WINDOWS.map((w) => (
          <button
            key={w.label}
            // Toggling a class based on state — React re-renders, the CSS
            // does the highlighting.
            className={w.minutes === minutes ? 'active' : ''}
            onClick={() => setMinutes(w.minutes)}
          >
            {w.label}
          </button>
        ))}
      </div>

      {points === null ? (
        <div className="chart-loading">loading…</div>
      ) : (
        <>
          {/* <>…</> is a Fragment: group siblings without an extra div. */}
          <Sparkline
            points={points}
            field="util_pct"
            label="utilization %"
            color="var(--accent-util)"
          />
          <Sparkline
            points={points}
            field="mem_pct"
            label="memory %"
            color="var(--accent-mem)"
          />
        </>
      )}
    </div>
  )
}
