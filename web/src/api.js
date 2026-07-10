// === api.js: plain-JS fetch helpers =========================================
// Not everything needs to be a React component! Data access is ordinary
// JavaScript; components import these functions and call them from hooks.
//
// Every request includes the session cookie automatically because the app and
// the API share an origin (in dev, the Vite proxy makes it look that way).

// Small wrapper: throw on non-2xx so callers can use try/catch, and decode
// JSON in one place.
async function request(url, options = {}) {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 401) {
    // Signal "not logged in" distinctly so the app can show the login page.
    const err = new Error('unauthorized')
    err.unauthorized = true
    throw err
  }
  if (!res.ok) {
    throw new Error(`${url} failed: HTTP ${res.status}`)
  }
  // 204 No Content (logout) has no body to parse.
  return res.status === 204 ? null : res.json()
}

export const api = {
  // Who am I? Used on app load to restore an existing session.
  me: () => request('/api/me'),

  login: (username, password) =>
    request('/api/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request('/api/logout', { method: 'POST' }),

  // Latest sample for every server (the dashboard poll).
  current: () => request('/api/current'),

  // Downsampled time series for one GPU. minutes controls the window.
  history: (server, gpu, minutes, points = 300) =>
    request(
      `/api/history?server=${encodeURIComponent(server)}&gpu=${gpu}` +
        `&minutes=${minutes}&points=${points}`,
    ),
}
