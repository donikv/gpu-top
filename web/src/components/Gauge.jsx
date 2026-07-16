// === Gauge.jsx: the simplest kind of component ==============================
// React concept: a pure "presentational" component. No state, no effects —
// just props in, JSX out. Given the same props it always renders the same
// thing, which makes it trivial to reason about and reuse.
export default function Gauge({ label, value }) {
  const pct = value == null ? 0 : Math.min(100, Math.max(0, value))
  // Threshold-based status color (calm / warning / critical) — computed as a
  // class name so the actual colors live in the CSS theme, not in JS.
  const level = pct >= 90 ? 'critical' : pct >= 70 ? 'warning' : 'ok'
  return (
    <div className="gauge">
      <div className="gauge-label">
        <span>{label}</span>
        <span>{value == null ? '–' : `${Math.round(pct)}%`}</span>
      </div>
      <div className="gauge-track">
        {/* Inline style is the right tool here because the width is genuinely
            dynamic; static styling belongs in the CSS file. */}
        <div className={`gauge-fill ${level}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
