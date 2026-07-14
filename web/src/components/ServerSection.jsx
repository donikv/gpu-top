// === ServerSection.jsx: one GPU server ======================================
// React concept: composition. This component is mostly layout — it arranges
// smaller, dumber components (GpuCard, ProcessTable, StaleBadge) and passes
// each the slice of data it needs. Small single-purpose components are what
// keep React apps readable.
import GpuCard from './GpuCard'
import ProcessTable from './ProcessTable'
import StaleBadge from './StaleBadge'

export default function ServerSection({ server, win }) {
  return (
    // Template-literal className: append the modifier class only when stale.
    <section className={`server-section${server.stale ? ' stale' : ''}`}>
      <div className="server-header">
        <h2>{server.name}</h2>
        <StaleBadge lastSeen={server.last_seen} stale={server.stale} />
      </div>

      <div className="gpu-grid">
        {server.gpus.map((gpu) => (
          <GpuCard key={gpu.gpu_index} serverName={server.name} gpu={gpu} win={win} />
        ))}
      </div>

      {/* Render the table only if something is running. `list.length > 0 &&`
          is the usual JSX idiom for "show this section only when non-empty". */}
      {server.processes.length > 0 && <ProcessTable processes={server.processes} />}
    </section>
  )
}
