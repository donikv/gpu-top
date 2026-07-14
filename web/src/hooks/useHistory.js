// === useHistory.js: data fetching with cancellation =========================
// React concepts: fetching in useEffect, AbortController cleanup, and
// loading/error state. This hook loads the time series for one GPU and
// refreshes it periodically (less often than the live numbers — history
// changes slowly and the query is heavier).
import { useEffect, useState } from 'react'
import { api } from '../api'

const REFRESH_MS = 10000

export function useHistory(server, gpu, minutes) {
  // history = { points, since, until } — since/until are the requested time
  // window so charts can place partial data correctly. null = still loading.
  const [history, setHistory] = useState(null)

  useEffect(() => {
    // When dependencies change (e.g. the user picks a different time window),
    // React first runs the previous effect's cleanup, then this effect again.
    // `cancelled` makes sure a slow response from the OLD request can't
    // overwrite data from the NEW one — a classic fetch race.
    let cancelled = false

    const load = () =>
      api
        .history(server, gpu, minutes)
        .then((data) => {
          if (!cancelled) setHistory(data)
        })
        .catch(() => {
          if (!cancelled) setHistory({ points: [], since: 0, until: 0 })
        })

    setHistory(null) // show the loading state while the new window loads
    load()
    const id = setInterval(load, REFRESH_MS)

    return () => {
      cancelled = true
      clearInterval(id)
    }
    // Re-run whenever WHAT we're looking at changes. If a dependency is
    // missing from this array, the hook would keep showing stale data —
    // eslint's react-hooks plugin exists to catch exactly that.
  }, [server, gpu, minutes])

  return history
}
