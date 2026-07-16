// === ClusterView.jsx: the whole fleet on one screen =========================
// A column per server; in each column two compact charts (utilization and
// memory) with ONE LINE PER GPU. All data arrives in a single /api/cluster
// response via useCluster — no per-card fetching here.
import { useCluster } from '../hooks/useCluster'
import MultiSparkline from './MultiSparkline'
import StaleBadge from './StaleBadge'

// Fixed color per GPU index, same palette family as the rest of the app.
// Assigned by index so "GPU 0 is always blue" holds on every server.
const GPU_COLORS = [
  '#3987e5', '#199e70', '#c98500', '#9085e9',
  '#e66767', '#d55181', '#d95926', '#008300',
]
const gpuColor = (i) => GPU_COLORS[i % GPU_COLORS.length]

export default function ClusterView({ liveServers, visibleNames, win }) {
  const cluster = useCluster(win)

  if (cluster === null) {
    return <div className="banner">Loading cluster overview…</div>
  }

  // /api/cluster knows the history; /api/current (passed down as liveServers)
  // knows freshness. Join the two by name here in render — derived data, no
  // extra state needed.
  const liveByName = Object.fromEntries(liveServers.map((s) => [s.name, s]))
  const servers = cluster.servers.filter(
    (s) => visibleNames.size === 0 || visibleNames.has(s.name),
  )

  if (servers.length === 0) {
    return <div className="banner">No history in this window yet.</div>
  }

  return (
    <div className="cluster-grid">
      {servers.map((server) => {
        const live = liveByName[server.name]
        return (
          <div
            key={server.name}
            className={`cluster-cell${live?.stale ? ' stale' : ''}`}
          >
            <div className="cluster-cell-head">
              <span className="cluster-name">{server.name}</span>
              {live && <StaleBadge lastSeen={live.last_seen} stale={live.stale} />}
            </div>

            {/* one legend per server: a colored dot per GPU */}
            <div className="cluster-legend">
              {server.gpus.map((g) => (
                <span key={g.gpu_index} style={{ color: gpuColor(g.gpu_index) }}>
                  ● GPU{g.gpu_index}
                </span>
              ))}
            </div>

            <MultiSparkline
              label="utilization %"
              field="util_pct"
              since={cluster.since}
              until={cluster.until}
              series={server.gpus.map((g) => ({
                key: g.gpu_index,
                color: gpuColor(g.gpu_index),
                points: g.points,
              }))}
            />
            <MultiSparkline
              label="memory %"
              field="mem_pct"
              since={cluster.since}
              until={cluster.until}
              series={server.gpus.map((g) => ({
                key: g.gpu_index,
                color: gpuColor(g.gpu_index),
                points: g.points,
              }))}
            />
          </div>
        )
      })}
    </div>
  )
}
