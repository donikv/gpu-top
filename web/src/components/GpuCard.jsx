// === GpuCard.jsx: one GPU's live numbers + history charts ===================
// React concepts:
//   * props are read-only inputs. The time window (`win`) deliberately lives
//     in Dashboard, not here — ONE picker drives every chart on the page, so
//     the cards just receive it and stay in sync ("lifting state up").
import { useHistory } from '../hooks/useHistory'
import Gauge from './Gauge'
import Sparkline from './Sparkline'

// Plain data + tiny helpers can live next to the component. Not everything
// needs to be React.
const fmt = (v, suffix = '') => (v == null ? '–' : `${Math.round(v)}${suffix}`)

export default function GpuCard({ serverName, gpu, win }) {
  // Hooks compose: this custom hook re-fetches whenever the window changes,
  // because the window fields are in its dependency array.
  const history = useHistory(serverName, gpu.gpu_index, win)

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

      {history === null ? (
        <div className="chart-loading">loading…</div>
      ) : (
        <>
          {/* <>…</> is a Fragment: group siblings without an extra div. */}
          <Sparkline
            history={history}
            field="util_pct"
            label="utilization %"
            color="var(--accent-util)"
          />
          <Sparkline
            history={history}
            field="mem_pct"
            label="memory %"
            color="var(--accent-mem)"
          />
        </>
      )}
    </div>
  )
}
