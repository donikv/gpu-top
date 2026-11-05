// === DiagnosticsPage.jsx: raw samples + collection gaps for one server =====
// Reached only by URL: #/diag?server=zver3&from=2026-11-05T14:20&to=…
// The dashboard charts average samples into buckets; for incident forensics
// you want the opposite — every sample with its exact timestamp, and an
// explicit list of the stretches where NO sample arrived.
//
// React concepts:
//   * the URL as state - the committed selection lives in location.hash, so
//     a diagnostics view is a link you can paste to a colleague. The form
//     holds a local draft; "Load" writes the hash, App re-renders us with
//     the new `route`, and the fetch effect picks it up.
//   * useMemo - the table rows (samples interleaved with gap markers) are
//     derived from the response and only rebuilt when the response changes.
import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

// "YYYY-MM-DDTHH:MM[:SS]" (local time, what <input type=datetime-local>
// speaks) <-> epoch seconds (what the API speaks).
const toEpoch = (local) => new Date(local).getTime() / 1000
const toLocal = (epoch) => {
  const d = new Date(epoch * 1000)
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 16)
}

const pad = (n) => String(n).padStart(2, '0')
function fmtTime(epoch, withDate) {
  const d = new Date(epoch * 1000)
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  if (!withDate) return time
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
}
function fmtDur(s) {
  if (s < 90) return `${s.toFixed(1)}s`
  if (s < 90 * 60) return `${Math.floor(s / 60)}m ${pad(Math.round(s % 60))}s`
  return `${Math.floor(s / 3600)}h ${pad(Math.round((s % 3600) / 60))}m`
}
const num = (v, digits = 0) => (v == null ? 'n/a' : v.toFixed(digits))

const GAP_NOTE = {
  all: 'no samples in this window at all',
  start: 'no samples from window start until here',
  between: 'no samples',
  end: 'no samples after this until window end',
}

// Heuristic highlights, not hard limits: most data-center GPUs start
// thermal-throttling in the mid-80s, and drawing ≥98% of the power limit
// means the GPU is power-capped.
const tempClass = (t) => (t != null && t >= 85 ? 'warn' : '')
const powerClass = (g) =>
  g.power_w != null && g.power_limit_w > 0 && g.power_w >= 0.98 * g.power_limit_w
    ? 'warn'
    : ''

function parseRoute(route) {
  const q = new URLSearchParams(route.split('?')[1] || '')
  return { server: q.get('server') || '', from: q.get('from') || '', to: q.get('to') || '' }
}

// Plain JS: build a CSV in memory and hand it to the browser as a download.
function download(filename, rows) {
  const csv = rows.map((r) => r.map((v) => (v == null ? '' : v)).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([csv + '\n'], { type: 'text/csv' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  a.click()
  URL.revokeObjectURL(url)
}

export default function DiagnosticsPage({ route, user, onLogout }) {
  const committed = parseRoute(route)

  // Draft form state, seeded from the URL (or "the last 30 minutes").
  const now = Date.now() / 1000
  const [server, setServer] = useState(committed.server)
  const [from, setFrom] = useState(committed.from || toLocal(now - 1800))
  const [to, setTo] = useState(committed.to || toLocal(now))

  const [servers, setServers] = useState([])
  useEffect(() => {
    api.servers().then((list) => {
      setServers(list)
      setServer((cur) => cur || list[0]?.name || '')
    }).catch(() => {})
  }, [])

  // { status: 'idle'|'loading'|'ok'|'error', data, error }
  const [result, setResult] = useState({ status: 'idle' })
  // Bumped by "Load" when the URL wouldn't change (same range clicked again,
  // e.g. to refresh a window that ends now): forces the effect to re-run.
  const [reloads, setReloads] = useState(0)
  useEffect(() => {
    const { server: s, from: f, to: t } = committed
    if (!s || !f || !t) return
    let cancelled = false // same stale-response guard as useHistory
    setResult({ status: 'loading' })
    api
      .diagnostics(s, toEpoch(f), toEpoch(t))
      .then((data) => !cancelled && setResult({ status: 'ok', data }))
      .catch((error) => !cancelled && setResult({ status: 'error', error }))
    return () => {
      cancelled = true
    }
  }, [committed.server, committed.from, committed.to, reloads])

  const load = (e) => {
    e.preventDefault()
    const next = `#/diag?${new URLSearchParams({ server, from, to })}`
    if (window.location.hash === next) setReloads((n) => n + 1)
    else window.location.hash = next // -> hashchange -> new `route` prop
  }

  const data = result.status === 'ok' ? result.data : null
  const multiDay =
    data && new Date(data.since * 1000).toDateString() !== new Date(data.until * 1000).toDateString()
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone

  // Interleave gap markers with sample rows, in time order.
  const rows = useMemo(() => {
    if (!data) return []
    const after = new Map() // sample ts -> gap that follows it
    const out = []
    for (const g of data.gaps) {
      if (g.kind === 'start' || g.kind === 'all') out.push({ gap: g })
      else after.set(g.start, g)
    }
    for (const s of data.samples) {
      out.push({ sample: s, byGpu: new Map(s.gpus.map((g) => [g.gpu_index, g])) })
      if (after.has(s.ts)) out.push({ gap: after.get(s.ts) })
    }
    return out
  }, [data])

  // Per-GPU peaks across the window, for the summary row.
  const peaks = useMemo(() => {
    const p = new Map()
    for (const s of data?.samples ?? []) {
      for (const g of s.gpus) {
        const cur = p.get(g.gpu_index) ?? { temp: null, power: null }
        if (g.temp_c != null && (cur.temp == null || g.temp_c > cur.temp)) cur.temp = g.temp_c
        if (g.power_w != null && (cur.power == null || g.power_w > cur.power)) cur.power = g.power_w
        p.set(g.gpu_index, cur)
      }
    }
    return p
  }, [data])

  const csvSamples = () =>
    download(`gpu-top-${data.server}-${committed.from}-samples.csv`, [
      ['time_local', 'epoch', 'gpu', 'temp_c', 'power_w', 'power_limit_w',
        'util_pct', 'mem_used_mib', 'mem_total_mib', 'fan_pct'],
      ...data.samples.flatMap((s) =>
        s.gpus.map((g) => [fmtTime(s.ts, true), s.ts.toFixed(3), g.gpu_index, g.temp_c,
          g.power_w, g.power_limit_w, g.util_pct, g.mem_used_mib, g.mem_total_mib, g.fan_pct]),
      ),
    ])
  const csvGaps = () =>
    download(`gpu-top-${data.server}-${committed.from}-gaps.csv`, [
      ['start_local', 'end_local', 'start_epoch', 'end_epoch', 'seconds', 'kind'],
      ...data.gaps.map((g) => [fmtTime(g.start, true), fmtTime(g.end, true),
        g.start.toFixed(3), g.end.toFixed(3), g.seconds.toFixed(1), g.kind]),
    ])

  const cols = 1 + 2 * (data?.gpus.length ?? 0)

  return (
    <div className="dashboard">
      <header className="topbar">
        <a href="#/">
          <img src="/android-chrome-192x192.png" alt="gpu-top" className="logo" />
        </a>
        <h1>Diagnostics</h1>
        <div className="topbar-right">
          <a href="#/" className="back-link">← Dashboard</a>
          <span className="user">{user}</span>
          <button onClick={onLogout}>Log out</button>
        </div>
      </header>

      <form className="controls-bar diag-form" onSubmit={load}>
        <select value={server} onChange={(e) => setServer(e.target.value)}>
          {servers.map((s) => (
            <option key={s.name} value={s.name}>{s.name}</option>
          ))}
        </select>
        <span className="range-inputs">
          <input type="datetime-local" step="1" value={from} onChange={(e) => setFrom(e.target.value)} />
          <span className="range-sep">→</span>
          <input type="datetime-local" step="1" value={to} onChange={(e) => setTo(e.target.value)} />
          <button type="submit" disabled={!server || !from || !to || toEpoch(to) <= toEpoch(from)}>
            Load
          </button>
        </span>
        {data && (
          <span className="diag-downloads">
            <button type="button" onClick={csvSamples}>Samples CSV</button>
            <button type="button" onClick={csvGaps}>Gaps CSV</button>
          </span>
        )}
      </form>

      {result.status === 'idle' && (
        <div className="banner">
          Pick a server and a time range. Shows every raw sample (no averaging) and
          every stretch where no sample arrived.
        </div>
      )}
      {result.status === 'loading' && <div className="banner">Loading…</div>}
      {result.status === 'error' && (
        <div className="banner error">{result.error.message}</div>
      )}

      {data && (
        <>
          <div className="banner diag-summary">
            <strong>{data.server}</strong> · {data.samples.length} samples · one every ~
            {data.interval_s.toFixed(1)}s · gap = no sample for &gt;
            {data.gap_threshold_s.toFixed(1)}s · times in {zone}
          </div>
          {data.since < data.retained_since && (
            <div className="banner error">
              Part of this window is older than the retention period: samples before{' '}
              {fmtTime(data.retained_since, true)} have been pruned, so missing data
              there is NOT a collection gap.
            </div>
          )}

          <h2 className="diag-h2">Collection gaps</h2>
          {data.gaps.length === 0 ? (
            <p className="diag-none">None. Samples arrived continuously.</p>
          ) : (
            <div className="proc-table-wrap">
              <table className="proc-table diag-gaps">
                <thead>
                  <tr><th>from</th><th>to</th><th className="num">duration</th><th>note</th></tr>
                </thead>
                <tbody>
                  {data.gaps.map((g) => (
                    <tr key={g.start}>
                      <td>{fmtTime(g.start, multiDay)}</td>
                      <td>{fmtTime(g.end, multiDay)}</td>
                      <td className="num">{fmtDur(g.seconds)}</td>
                      <td>{GAP_NOTE[g.kind]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className="diag-h2">Samples</h2>
          {data.samples.length > 0 && (
            <div className="proc-table-wrap diag-scroll">
              <table className="proc-table diag-table">
                <thead>
                  <tr>
                    <th rowSpan="2">time</th>
                    {data.gpus.map((g) => (
                      <th key={g.index} colSpan="2" className="gpu-head" title={g.name}>
                        GPU {g.index}
                      </th>
                    ))}
                  </tr>
                  <tr>
                    {data.gpus.map((g) => [
                      <th key={`t${g.index}`} className="num gpu-start">°C</th>,
                      <th key={`p${g.index}`} className="num">W</th>,
                    ])}
                  </tr>
                  <tr className="peak-row">
                    <th>peak</th>
                    {data.gpus.map((g) => [
                      <th key={`t${g.index}`} className={`num gpu-start ${tempClass(peaks.get(g.index)?.temp)}`}>
                        {num(peaks.get(g.index)?.temp)}
                      </th>,
                      <th key={`p${g.index}`} className="num">{num(peaks.get(g.index)?.power)}</th>,
                    ])}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) =>
                    r.gap ? (
                      <tr key={`gap${r.gap.start}`} className="gap-row">
                        <td colSpan={cols}>
                          ⚠ {GAP_NOTE[r.gap.kind]} for {fmtDur(r.gap.seconds)} (
                          {fmtTime(r.gap.start, multiDay)} → {fmtTime(r.gap.end, multiDay)})
                        </td>
                      </tr>
                    ) : (
                      <tr key={r.sample.ts} className={r.byGpu.size < data.gpus.length ? 'partial' : ''}>
                        <td>{fmtTime(r.sample.ts, multiDay)}</td>
                        {data.gpus.map((gpu) => {
                          const g = r.byGpu.get(gpu.index)
                          if (!g) {
                            // A GPU nvidia-smi stopped reporting (fell off the bus?)
                            return [
                              <td key={`t${gpu.index}`} className="num gpu-start missing" title="GPU missing from this sample">—</td>,
                              <td key={`p${gpu.index}`} className="num missing">—</td>,
                            ]
                          }
                          return [
                            <td key={`t${gpu.index}`} className={`num gpu-start ${tempClass(g.temp_c)}`}>{num(g.temp_c)}</td>,
                            <td key={`p${gpu.index}`} className={`num ${powerClass(g)}`}
                              title={g.power_limit_w != null ? `limit ${num(g.power_limit_w)} W` : undefined}>
                              {num(g.power_w)}
                            </td>,
                          ]
                        })}
                      </tr>
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
