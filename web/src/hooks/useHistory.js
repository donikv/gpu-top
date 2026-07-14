// === useHistory.js: data fetching with cancellation and self-healing ========
// React concepts: fetching in useEffect, cleanup, and defensive scheduling.
// A dashboard tab lives in the background a lot, and browsers throttle timers
// in hidden tabs — so besides the periodic refresh this hook also refetches
// the moment the tab becomes visible again, and retries quickly while the
// data is still sparse (a freshly deployed agent) or a fetch failed.
import { useEffect, useState } from 'react'
import { api } from '../api'

const REFRESH_MS = 10000 // normal cadence: history moves slowly
const RETRY_MS = 3000    // sparse data or a failed fetch: check back sooner

export function useHistory(server, gpu, win) {
  // history = { points, since, until } — since/until are the requested time
  // window so charts can place partial data correctly. null = still loading.
  // `win` is { minutes: N } (rolling, keeps refreshing) or { start, end }
  // (a fixed range in the past — fetched once, nothing new can appear).
  const [history, setHistory] = useState(null)

  useEffect(() => {
    // `cancelled` guards against the fetch race: when deps change, React runs
    // this effect's cleanup first, so a slow response from the OLD request
    // can't overwrite data from the NEW one.
    let cancelled = false
    let timer = null
    const isFixedRange = win.start != null

    // A setTimeout CHAIN instead of setInterval: each response schedules the
    // next fetch, so the delay can adapt (fast while sparse/failing) and a
    // slow response never stacks up behind an impatient interval.
    const tick = () => {
      api
        .history(server, gpu, win)
        .then((data) => {
          if (cancelled) return
          setHistory(data)
          if (!isFixedRange) {
            timer = setTimeout(tick, data.points.length < 2 ? RETRY_MS : REFRESH_MS)
          }
        })
        .catch(() => {
          if (cancelled) return
          // keep the last good data on a failed refresh; only show the empty
          // state if we never had data for this window
          setHistory((prev) => prev ?? { points: [], since: 0, until: 0 })
          timer = setTimeout(tick, RETRY_MS)
        })
    }

    // Throttled background tabs can leave the chart stale for minutes; when
    // the user comes back, refetch immediately instead of waiting the timer out.
    const onVisible = () => {
      if (!document.hidden && !cancelled) {
        clearTimeout(timer)
        tick()
      }
    }
    document.addEventListener('visibilitychange', onVisible)

    setHistory(null) // show the loading state while the new window loads
    tick()

    return () => {
      cancelled = true
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
    // Re-run whenever WHAT we're looking at changes. The window object's
    // FIELDS are listed (not the object itself): a fresh-but-equal object
    // wouldn't needlessly refetch, and a changed field always does.
  }, [server, gpu, win.minutes, win.start, win.end])

  return history
}
