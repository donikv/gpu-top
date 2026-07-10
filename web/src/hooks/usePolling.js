// === usePolling.js: a custom hook ===========================================
// React concept: custom hooks. Any function whose name starts with "use" and
// which calls other hooks is a custom hook — a way to package stateful logic
// for reuse. Components that call usePolling() each get their OWN state and
// interval; hooks share logic, not data.
//
// This one fetches `fn` immediately and then every `intervalMs`, and returns
// { data, error }. The dashboard uses it to poll /api/current.
import { useEffect, useRef, useState } from 'react'

export function usePolling(fn, intervalMs) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  // The stale-closure pitfall: if we used `fn` directly inside setInterval,
  // the interval would forever call the version of `fn` captured on the first
  // render (closures capture variables at creation time). A ref is a mutable
  // box that survives re-renders, so the interval can always read the latest
  // fn through it without restarting the timer.
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    let cancelled = false

    const tick = async () => {
      try {
        const result = await fnRef.current()
        // After an await, the component may have unmounted (user logged out,
        // navigated away). Calling setState then is a wasted no-op React
        // warns about, so we bail out.
        if (!cancelled) {
          setData(result)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e)
      }
    }

    tick() // fetch immediately, don't wait a full interval for first data
    const id = setInterval(tick, intervalMs)

    // The cleanup function: React runs this when the component unmounts or
    // when a dependency changes (before re-running the effect). Forgetting to
    // clear intervals here is the classic React memory-leak bug.
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // Dependency array: the effect restarts only if intervalMs changes.
  }, [intervalMs])

  return { data, error }
}
