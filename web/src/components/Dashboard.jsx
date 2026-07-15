// === Dashboard.jsx: the main screen =========================================
// React concepts:
//   * derived state - `visible` is computed from existing state during render,
//     NOT stored with useState. Storing it too would create two sources of
//     truth that can drift apart. Rule of thumb: if you can compute it,
//     compute it.
//   * immutable state updates - state must be REPLACED, never mutated:
//     selected.add(x) on the existing Set would change the object in place,
//     React would see the same reference and skip the re-render. So the
//     toggle builds a new Set each time.
//   * rendering lists with .map() and the key prop - keys tell React which
//     rendered item corresponds to which data item across re-renders, so it
//     can update in place instead of rebuilding (and so component state stays
//     with the right item).
import { useState } from 'react'
import { api } from '../api'
import { usePolling } from '../hooks/usePolling'
import ClusterView from './ClusterView'
import ServerFilter from './ServerFilter'
import ServerSection from './ServerSection'
import WindowPicker from './WindowPicker'

const POLL_MS = 2000

export default function Dashboard({ user, onLogout }) {
  // Poll /api/current every 2s. Every response updates `data`, which
  // re-renders this component and everything below it with fresh numbers.
  // The server returns the list already in natural order (hydra before zver,
  // zver2 before zver10), so no sorting is needed here.
  const { data, error } = usePolling(api.current, POLL_MS)

  // The selected subset of servers. Empty Set = no filter = show everything.
  const [selected, setSelected] = useState(new Set())

  // ONE time window for every chart on the page ("lifting state up"):
  // { minutes: N } for a live rolling window, { start, end } for a fixed
  // range in the past. Owned here, rendered by WindowPicker, consumed by
  // every GpuCard's useHistory.
  const [win, setWin] = useState({ minutes: 60 })

  // Two ways to look at the fleet: detailed per-server cards, or the compact
  // cluster overview (all servers side by side, one line per GPU).
  const [view, setView] = useState('cards') // 'cards' | 'cluster'

  const servers = data ? data.servers : []

  const toggle = (name) =>
    setSelected((prev) => {
      const next = new Set(prev) // copy, don't mutate (see header comment)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  // Derived state: just a filter expression, recomputed each render.
  const visible = selected.size === 0
    ? servers
    : servers.filter((s) => selected.has(s.name))

  return (
    <div className="dashboard">
      <header className="topbar">
        {/* files in web/public/ are served from the site root as-is */}
        <img src="/android-chrome-192x192.png" alt="gpu-top" className="logo" />

        {/* Server filter: chips while they fit on one row, a Grafana-style
            multi-select dropdown once they'd wrap (ServerFilter measures). */}
        <ServerFilter
          servers={servers}
          selected={selected}
          toggle={toggle}
          clear={() => setSelected(new Set())}
        />

        <div className="topbar-right">
          <span className="user">{user}</span>
          <button onClick={onLogout}>Log out</button>
        </div>
      </header>

      {/* second control row, below the topbar's dividing line */}
      <div className="controls-bar">
        <WindowPicker value={win} onChange={setWin} />

        {/* view toggle: same chip styling, single on/off state */}
        <button
          className={`chip${view === 'cluster' ? ' active' : ''}`}
          onClick={() => setView(view === 'cluster' ? 'cards' : 'cluster')}
        >
          Cluster overview
        </button>
      </div>

      {error && (
        <div className="banner error">
          Failed to reach the server: {error.message}
        </div>
      )}

      {data && servers.length === 0 && (
        <div className="banner">
          No agents have reported yet. Start gpu-top-agent on a GPU server.
        </div>
      )}

      {view === 'cluster' ? (
        <ClusterView liveServers={servers} visibleNames={selected} win={win} />
      ) : (
        visible.map((server) => (
          // Composition: Dashboard doesn't know how a server is drawn; it
          // just hands each server object down as a prop.
          <ServerSection key={server.name} server={server} win={win} />
        ))
      )}
    </div>
  )
}
