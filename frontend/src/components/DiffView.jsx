import { useEffect } from 'react'
import TurnChanges from './TurnChanges.jsx'

// Cumulative changes since the feed was loaded, rendered with the same rich
// map/table widgets as the per-turn inline view.
export default function DiffView({ data, feed, busy, onLoad }) {
  useEffect(() => { if (!data && !busy) onLoad() }, [])

  if (busy && !data) {
    return <div className="diff"><div className="empty"><span className="spinner" /> computing changes…</div></div>
  }
  if (!data) {
    return <div className="diff"><div className="empty"><button className="primary" onClick={onLoad}>Show changes</button></div></div>
  }
  if (data.error) {
    return <div className="diff"><div className="empty">Could not load changes: {data.error}</div></div>
  }
  const has = data.diff?.records?.length || data.changes?.length
  if (!has) {
    return <div className="diff"><div className="empty">No changes yet — the feed matches the original.</div></div>
  }
  return (
    <div className="diff">
      <div className="diff-head">All changes since the feed was loaded
        <button className="ghost" onClick={onLoad} disabled={busy}>{busy ? '…' : 'refresh'}</button>
      </div>
      <div className="diff-body"><TurnChanges diff={data.diff} feed={feed} /></div>
    </div>
  )
}
