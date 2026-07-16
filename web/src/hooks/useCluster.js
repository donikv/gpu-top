// === useCluster.js: one fetch for the whole cluster overview ================
// Same self-healing pattern as useHistory (adaptive timeout chain + refetch
// on tab visibility), but for /api/cluster, which returns every server's
// per-GPU series in a single response.
import { useEffect, useState } from 'react'
import { api } from '../api'

const REFRESH_MS = 10000
const RETRY_MS = 3000

export function useCluster(win) {
  const [cluster, setCluster] = useState(null)

  useEffect(() => {
    let cancelled = false
    let timer = null
    const isFixedRange = win.start != null

    const tick = () => {
      api
        .cluster(win)
        .then((data) => {
          if (cancelled) return
          setCluster(data)
          if (!isFixedRange) timer = setTimeout(tick, REFRESH_MS)
        })
        .catch(() => {
          if (cancelled) return
          setCluster((prev) => prev ?? { servers: [], since: 0, until: 0 })
          timer = setTimeout(tick, RETRY_MS)
        })
    }

    const onVisible = () => {
      if (!document.hidden && !cancelled) {
        clearTimeout(timer)
        tick()
      }
    }
    document.addEventListener('visibilitychange', onVisible)

    setCluster(null)
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [win.minutes, win.start, win.end])

  return cluster
}
