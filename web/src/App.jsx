// === App.jsx: the root component ============================================
// React concepts here:
//   * useState  - a piece of component memory; changing it re-renders the tree
//   * useEffect - run side effects (like fetching) after render
//   * conditional rendering - return different JSX based on state
//   * "lifting state up" - `user` lives here, the common ancestor, because
//     both LoginPage (sets it) and Dashboard (shows it) need it.
import { useEffect, useState } from 'react'
import { api } from './api'
import Dashboard from './components/Dashboard'
import DiagnosticsPage from './components/DiagnosticsPage'
import LoginPage from './components/LoginPage'

export default function App() {
  // user is one of:
  //   undefined -> we haven't checked the session yet (show nothing / loading)
  //   null      -> checked, not logged in (show LoginPage)
  //   "alice"   -> logged in (show Dashboard)
  const [user, setUser] = useState(undefined)
  // Hooks must run on every render in the same order, so this sits up here
  // with the others — not after the early returns below.
  const route = useHashRoute()

  // On first render, ask the server whether our session cookie is still valid.
  // The empty dependency array [] means "run this effect once after the first
  // render", i.e. on mount — the React equivalent of window.onload.
  useEffect(() => {
    api
      .me()
      .then((data) => setUser(data.user))
      .catch(() => setUser(null))
  }, [])

  if (user === undefined) {
    return <div className="loading">Loading…</div>
  }

  // Conditional rendering: components are just functions returning JSX, so a
  // plain if/else (or ternary) decides what the user sees. When setUser is
  // called, React re-runs App and the other branch appears.
  if (user === null) {
    // Passing a function as a prop: LoginPage calls onLogin(username) after a
    // successful login, which updates state *here* and swaps in the Dashboard.
    return <LoginPage onLogin={setUser} />
  }

  const handleLogout = async () => {
    await api.logout().catch(() => {})
    setUser(null)
  }

  // Minimal hash routing, no router library: '#/diag?...' shows the
  // diagnostics page, anything else the dashboard. Hash URLs never reach the
  // server, so links like '#/diag?server=zver3&from=…' are shareable as-is.
  if (route.startsWith('#/diag')) {
    return <DiagnosticsPage route={route} user={user} onLogout={handleLogout} />
  }
  return <Dashboard user={user} onLogout={handleLogout} />
}

// Custom hook: the current location.hash as state, updated on navigation.
function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}
