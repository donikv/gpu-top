// === ProcessTable.jsx: rendering tabular data ===============================
// React concept: keys in lists, with a subtlety. A PID alone isn't unique
// enough here — after a reboot PIDs recycle, and a process can show up on two
// GPUs — so the key combines GPU index and PID. Keys only need to be unique
// among siblings, not globally.
export default function ProcessTable({ processes }) {
  return (
    // The wrapper div is what scrolls horizontally on narrow screens — the
    // table keeps its natural width inside it, so the page itself never
    // scrolls sideways (see .proc-table-wrap in styles.css).
    <div className="proc-table-wrap">
    <table className="proc-table">
      <thead>
        <tr>
          <th>GPU</th>
          <th>PID</th>
          <th>User</th>
          <th>Container</th>
          <th className="num">Mem (MiB)</th>
          <th>Process</th>
        </tr>
      </thead>
      <tbody>
        {processes.map((p) => (
          <tr key={`${p.gpu_index}-${p.pid}`}>
            <td>{p.gpu_index >= 0 ? p.gpu_index : '?'}</td>
            <td>{p.pid}</td>
            <td>{p.user}</td>
            {/* `||` fallback: owner (from bind-mount heuristics) may be "" */}
            <td>{p.container}{p.owner ? ` (${p.owner})` : ''}</td>
            <td className="num">{p.mem_mib == null ? '–' : Math.round(p.mem_mib)}</td>
            <td className="proc-name">{p.name}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
