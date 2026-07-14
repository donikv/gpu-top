// === WindowPicker.jsx: one control, two shapes of state =====================
// React concept: a controlled component over a small "discriminated union".
// The selected window is either { minutes: N } (live, rolling) or
// { start, end } (a fixed range in the past, epoch seconds). The parent owns
// the value; this component only renders it and reports changes — which is
// what lets ONE picker drive every chart on the page.
import { useState } from 'react'

const PRESETS = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '6h', minutes: 360 },
  { label: '24h', minutes: 1440 },
]

// <input type="datetime-local"> speaks "YYYY-MM-DDTHH:MM" in local time;
// the API speaks epoch seconds. Two tiny converters bridge them.
const toEpoch = (localValue) => new Date(localValue).getTime() / 1000
const toLocal = (epoch) => {
  const d = new Date(epoch * 1000)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

export default function WindowPicker({ value, onChange }) {
  // Local draft for the custom range: typing into the inputs shouldn't
  // refetch every chart on each keystroke — only "Apply" commits it upward.
  const [open, setOpen] = useState(false)
  const [from, setFrom] = useState(toLocal(Date.now() / 1000 - 3600))
  const [to, setTo] = useState(toLocal(Date.now() / 1000))

  const isRange = value.start != null
  const applyDisabled = !from || !to || toEpoch(to) <= toEpoch(from)

  return (
    <div className="window-picker global">
      {PRESETS.map((p) => (
        <button
          key={p.label}
          className={!isRange && value.minutes === p.minutes ? 'active' : ''}
          onClick={() => {
            setOpen(false)
            onChange({ minutes: p.minutes })
          }}
        >
          {p.label}
        </button>
      ))}
      <button
        className={isRange || open ? 'active' : ''}
        onClick={() => setOpen(!open)}
      >
        custom
      </button>

      {open && (
        <span className="range-inputs">
          <input
            type="datetime-local"
            value={from}
            max={to}
            onChange={(e) => setFrom(e.target.value)}
          />
          <span className="range-sep">→</span>
          <input
            type="datetime-local"
            value={to}
            onChange={(e) => setTo(e.target.value)}
          />
          <button
            disabled={applyDisabled}
            onClick={() => {
              onChange({ start: toEpoch(from), end: toEpoch(to) })
              setOpen(false)
            }}
          >
            Apply
          </button>
        </span>
      )}
    </div>
  )
}
