import { useEffect, useState } from 'react'
import { api } from '../api.js'

const PAGE = 500

// Lazy, paginated table viewer. Table names + counts come from feed.counts;
// rows are fetched a page at a time so huge tables (stop_times) never ship
// with the main feed payload.
export default function TableView({ feed, sid }) {
  const names = feed ? Object.keys(feed.counts || feed.tables || {}) : []
  const [active, setActive] = useState(null)
  const [page, setPage] = useState({ rows: [], headers: [], total: 0, offset: 0 })
  const [busy, setBusy] = useState(false)
  const current = active && names.includes(active) ? active : names[0]

  useEffect(() => { if (current && sid) load(current, 0) }, [current, sid])

  async function load(name, offset) {
    setBusy(true)
    try { setPage(await api.table(sid, name, offset, PAGE)) }
    finally { setBusy(false) }
  }

  if (!feed) return <div className="empty">No feed loaded.</div>

  const from = page.total ? page.offset + 1 : 0
  const to = Math.min(page.offset + PAGE, page.total)
  return (
    <div className="table-wrap">
      <div className="table-toolbar">
        <select value={current || ''} onChange={(e) => { setActive(e.target.value) }}>
          {names.map((n) => (
            <option key={n} value={n}>{n} ({feed.counts?.[n] ?? feed.tables?.[n]?.rows.length ?? 0})</option>
          ))}
        </select>
        <span style={{ color: 'var(--muted)', fontSize: 12 }}>
          {busy ? 'loading…' : `${page.headers.length} columns · rows ${from}–${to} of ${page.total}`}
        </span>
        <div className="spacer" style={{ flex: 1 }} />
        <button disabled={busy || page.offset === 0} onClick={() => load(current, Math.max(0, page.offset - PAGE))}>‹ Prev</button>
        <button disabled={busy || to >= page.total} onClick={() => load(current, page.offset + PAGE)}>Next ›</button>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr>{page.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>
            {page.rows.map((row, i) => (
              <tr key={i}>{page.headers.map((h) => <td key={h}>{row[h]}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
