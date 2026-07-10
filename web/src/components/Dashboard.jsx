// === Dashboard.jsx: the main screen =========================================
// React concepts:
//   * derived state - `visible` is computed from existing state during render,
//     NOT stored with useState. Storing it too would create two sources of
//     truth that can drift apart. Rule of thumb: if you can compute it,
//     compute it.
//   * rendering lists with .map() and the key prop - keys tell React which
//     rendered item corresponds to which data item across re-renders, so it
//     can update in place instead of rebuilding (and so component state stays
//     with the right item).
import { useState } from 'react'
import { api } from '../api'
import { usePolling } from '../hooks/usePolling'
import ServerSection from './ServerSection'

const POLL_MS = 2000

export default function Dashboard({ user, onLogout }) {
  // Poll /api/current every 2s. Every response updates `data`, which
  // re-renders this component and everything below it with fresh numbers.
  const { data, error } = usePolling(api.current, POLL_MS)

  // Which server the user wants to see; 'all' shows everything.
  const [filter, setFilter] = useState('all')

  const servers = data ? data.servers : []
  // Derived state: just a filter expression, recomputed each render.
  const visible = filter === 'all' ? servers : servers.filter((s) => s.name === filter)

  return (
    <div className="dashboard">
      <header className="topbar">
        <h1>gpu-top</h1>

        {/* A controlled <select>, same pattern as text inputs. */}
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All servers ({servers.length})</option>
          {servers.map((s) => (
            // key must be stable and unique among siblings; the server name
            // is both. Array indexes make poor keys when lists reorder.
            <option key={s.name} value={s.name}>
              {s.name}
            </option>
          ))}
        </select>

        <div className="topbar-right">
          <span className="user">{user}</span>
          <button onClick={onLogout}>Log out</button>
        </div>
      </header>

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

      {visible.map((server) => (
        // Composition: Dashboard doesn't know how a server is drawn; it just
        // hands each server object down as a prop.
        <ServerSection key={server.name} server={server} />
      ))}
    </div>
  )
}
