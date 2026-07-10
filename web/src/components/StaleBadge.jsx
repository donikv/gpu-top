// === StaleBadge.jsx: deriving display text from a timestamp =================
// Shows "live" (green) or "last seen 4m ago" (red). The parent already
// computed staleness server-side; this component only formats it.
//
// Note there's no timer here: the badge updates because the Dashboard's poll
// re-renders the whole tree every 2 seconds anyway. Adding a second timer
// inside this component would be redundant work — a common over-engineering
// trap in React.
function ago(tsSeconds) {
  const s = Math.max(0, Date.now() / 1000 - tsSeconds)
  if (s < 90) return `${Math.round(s)}s`
  if (s < 90 * 60) return `${Math.round(s / 60)}m`
  return `${Math.round(s / 3600)}h`
}

export default function StaleBadge({ lastSeen, stale }) {
  if (!stale) {
    return <span className="badge live">● live</span>
  }
  return <span className="badge stale">● last seen {ago(lastSeen)} ago</span>
}
