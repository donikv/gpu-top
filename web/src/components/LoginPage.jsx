// === LoginPage.jsx: forms the React way =====================================
// React concept: "controlled inputs". The input's value is driven by React
// state and every keystroke updates that state via onChange. The DOM never
// owns the text — React does. That's what makes validation, clearing the
// form, etc. trivial.
import { useState } from 'react'
import { api } from '../api'

// Props arrive as the function's single argument; destructuring `{ onLogin }`
// is the idiomatic way to unpack them.
export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e) => {
    // Stop the browser's default full-page form POST; we do it with fetch.
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const data = await api.login(username, password)
      onLogin(data.user) // tell the parent (App) — state lives up there
    } catch (err) {
      setError(err.unauthorized ? 'Invalid username or password' : err.message)
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>gpu-top</h1>
        <p className="login-hint">Sign in with your LDAP account</p>

        {/* value + onChange = controlled input */}
        <input
          type="text"
          placeholder="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
          autoComplete="username"
        />
        <input
          type="password"
          placeholder="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />

        {/* JSX conditional: render the error only when there is one */}
        {error && <div className="login-error">{error}</div>}

        <button type="submit" disabled={busy || !username || !password}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
