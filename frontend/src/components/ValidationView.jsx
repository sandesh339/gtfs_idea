import { useEffect } from 'react'

function download(report) {
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'validation-report.json'; a.click()
  URL.revokeObjectURL(url)
}

function Sample({ obj }) {
  const entries = Object.entries(obj).filter(([, v]) => v !== '' && v != null).slice(0, 6)
  return <div className="val-sample">{entries.map(([k, v]) => <span key={k}><b>{k}</b>: {String(v)}</span>)}</div>
}

export default function ValidationView({ report, busy, onRun }) {
  // auto-run once when the tab is opened for a feed with no cached report
  useEffect(() => { if (!report && !busy) onRun() }, [])

  if (busy && !report) {
    return <div className="val"><div className="empty"><span className="spinner" /> Running the GTFS validator…</div></div>
  }
  if (!report) {
    return <div className="val"><div className="empty"><button className="primary" onClick={onRun}>Run validation</button></div></div>
  }
  if (report.error) {
    return <div className="val"><div className="empty">Validation failed: {report.error}</div></div>
  }

  const sevClass = { ERROR: 'error', WARNING: 'warning', INFO: 'info' }
  return (
    <div className="val">
      <div className="val-head">
        <div className="val-counts">
          <span className="val-badge error">{report.error_count} errors</span>
          <span className="val-badge warning">{report.warning_count} warnings</span>
          <span className="val-src">{report.source}</span>
        </div>
        <div className="spacer" />
        <button onClick={onRun} disabled={busy}>{busy ? 'Re-running…' : 'Re-run'}</button>
        <button onClick={() => download(report)}>Download JSON</button>
      </div>

      {report.notices.length === 0 ? (
        <div className="val-clean">✓ No issues found — the feed is valid.</div>
      ) : (
        <div className="val-list">
          {report.notices.map((n, i) => (
            <details key={i} className={`val-notice ${sevClass[n.severity] || 'info'}`}>
              <summary>
                <span className={`val-chip ${sevClass[n.severity] || 'info'}`}>{n.severity}</span>
                <span className="val-code">{n.code}</span>
                <span className="val-count">×{n.count}</span>
              </summary>
              {n.samples?.length > 0 && (
                <div className="val-samples">
                  {n.samples.map((s, j) => <Sample key={j} obj={s} />)}
                </div>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  )
}
