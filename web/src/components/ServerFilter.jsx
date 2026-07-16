// === ServerFilter.jsx: chips that collapse into a dropdown ==================
// React concepts:
//   * refs to real DOM nodes (useRef) — sometimes you genuinely need to
//     MEASURE layout, which React state can't tell you.
//   * useLayoutEffect + ResizeObserver — re-measure synchronously after
//     render and whenever the container resizes, without polling.
//   * the trick itself: an invisible copy of the chip row is always rendered
//     (visibility:hidden, absolute). If its natural width exceeds the space
//     available, we render a Grafana-style multi-select dropdown instead of
//     the chips. Selection state and logic stay identical either way — only
//     the presentation switches.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'

export default function ServerFilter({ servers, selected, toggle, clear }) {
  const containerRef = useRef(null) // the space we may occupy
  const measureRef = useRef(null)   // invisible chip row, used only to measure
  const [collapsed, setCollapsed] = useState(false)
  const [open, setOpen] = useState(false)

  useLayoutEffect(() => {
    const update = () => {
      if (measureRef.current && containerRef.current) {
        setCollapsed(measureRef.current.scrollWidth > containerRef.current.clientWidth)
      }
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(containerRef.current)
    return () => ro.disconnect()
    // re-measure when the server list changes (new chip = new width)
  }, [servers])

  // Dropdown closes on any click outside of it — a document-level listener
  // added only while open, removed in the cleanup (no leaks, no dead handler).
  useEffect(() => {
    if (!open) return
    const onDocClick = (e) => {
      if (!containerRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const chips = (refProps = {}) => (
    <div className="server-chips" {...refProps}>
      <button
        className={`chip${selected.size === 0 ? ' active' : ''}`}
        onClick={clear}
      >
        All ({servers.length})
      </button>
      {servers.map((s) => (
        <button
          key={s.name}
          className={`chip${selected.has(s.name) ? ' active' : ''}${s.stale ? ' stale' : ''}`}
          onClick={() => toggle(s.name)}
        >
          {s.name}
        </button>
      ))}
    </div>
  )

  return (
    <div className="server-filter" ref={containerRef}>
      {/* always-rendered invisible measurer: tells us if chips would wrap */}
      <div className="server-chips chips-measure" ref={measureRef} aria-hidden="true">
        {chips().props.children}
      </div>

      {!collapsed ? (
        chips()
      ) : (
        <div className="server-dropdown">
          <button className="chip" onClick={() => setOpen(!open)}>
            {selected.size === 0
              ? `All servers (${servers.length})`
              : `${selected.size} of ${servers.length} servers`}
            <span className="caret">▾</span>
          </button>

          {open && (
            <div className="server-dropdown-panel">
              <label className="server-option">
                <input
                  type="checkbox"
                  checked={selected.size === 0}
                  onChange={clear}
                />
                All servers
              </label>
              {servers.map((s) => (
                <label
                  key={s.name}
                  className={`server-option${s.stale ? ' stale' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(s.name)}
                    onChange={() => toggle(s.name)}
                  />
                  {s.name}
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
