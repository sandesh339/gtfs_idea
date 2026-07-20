// Inline, per-turn "changes only" view. Given a structured diff, it auto-picks
// the right widget: an SVG mini-map for spatial changes, before->after tables
// for field edits, sequence diffs for stop_times, and an aggregate footer.
import { useState } from 'react'
import ExpandedMap from './ExpandedMap.jsx'

function project(coords, w, h, pad = 0.2) {
  const lons = coords.map((c) => c[0]), lats = coords.map((c) => c[1])
  let minLon = Math.min(...lons), maxLon = Math.max(...lons)
  let minLat = Math.min(...lats), maxLat = Math.max(...lats)
  const dLon = (maxLon - minLon) || 0.01, dLat = (maxLat - minLat) || 0.01
  minLon -= dLon * pad; maxLon += dLon * pad
  minLat -= dLat * pad; maxLat += dLat * pad
  return (lon, lat) => [
    ((lon - minLon) / (maxLon - minLon)) * w,
    h - ((lat - minLat) / (maxLat - minLat)) * h,
  ]
}

function stopLookup(feed) {
  const m = {}
  for (const s of feed?.tables?.['stops.txt']?.rows || []) {
    const lon = parseFloat(s.stop_lon), lat = parseFloat(s.stop_lat)
    if (Number.isFinite(lon) && Number.isFinite(lat)) m[s.stop_id] = { c: [lon, lat], name: s.stop_name || s.stop_id }
  }
  return m
}

// Build trip paths from stop_times sequence records by resolving each stop_id
// to its EXISTING coordinates in the feed (referenced stops already have coords).
function tripPaths(seqRecords, look) {
  const paths = [], stops = [], pts = []
  for (const r of seqRecords || []) {
    const beforeIds = new Set((r.seq_before || []).map((x) => x.stop_id))
    const line = []
    for (const st of r.seq_after || []) {
      const e = look[st.stop_id]
      if (!e) continue
      line.push(e.c); pts.push(e.c)
      stops.push({ c: e.c, isNew: !beforeIds.has(st.stop_id), name: e.name })
    }
    if (line.length) paths.push(line)
  }
  return { paths, stops, pts }
}

function MiniMap({ geoRecords, seqRecords, feed, onExpand }) {
  const W = 300, H = 170
  const look = stopLookup(feed)
  const { paths, stops: seqStops, pts: seqPts } = tripPaths(seqRecords, look)
  const pts = [...seqPts]
  for (const r of geoRecords) {
    if (r.geo?.after) pts.push(r.geo.after)
    if (r.geo?.before) pts.push(r.geo.before)
  }
  if (!pts.length) return null

  const allStops = feed?.tables?.['stops.txt']?.rows || []
  const bg = allStops.length && allStops.length < 80
    ? allStops.map((s) => [parseFloat(s.stop_lon), parseFloat(s.stop_lat)])
        .filter((c) => Number.isFinite(c[0]) && Number.isFinite(c[1]))
    : []

  const p = project(pts.concat(bg.length ? bg : []), W, H)
  const inBox = ([x, y]) => x >= -4 && x <= W + 4 && y >= -4 && y <= H + 4

  return (
    <div className="minimap-wrap" onClick={onExpand} title="Click to enlarge">
      <svg className="minimap" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        {bg.map((c, i) => {
          const [x, y] = p(c[0], c[1])
          return inBox([x, y]) ? <circle key={'b' + i} cx={x} cy={y} r="2.5" fill="#c7cbd4" /> : null
        })}
        {paths.map((line, i) => (
          <path key={'p' + i} d={line.map((c, j) => { const [x, y] = p(c[0], c[1]); return `${j ? 'L' : 'M'}${x},${y}` }).join(' ')}
            fill="none" stroke="#4f46e5" strokeWidth="2" opacity="0.7" />
        ))}
        {seqStops.map((s, i) => {
          const [x, y] = p(s.c[0], s.c[1])
          return <g key={'ss' + i}>
            <circle cx={x} cy={y} r={s.isNew ? 5 : 3.5} fill={s.isNew ? '#059669' : '#2563eb'} stroke="#fff" strokeWidth="1.4" />
            {s.isNew && <text x={x + 7} y={y + 3} fontSize="10" fill="#374151">{s.name}</text>}
          </g>
        })}
        {geoRecords.map((r, i) => {
          const a = r.geo.after && p(r.geo.after[0], r.geo.after[1])
          const b = r.geo.before && p(r.geo.before[0], r.geo.before[1])
          const color = r.kind === 'added' ? '#059669' : r.kind === 'removed' ? '#dc2626' : '#2563eb'
          return (
            <g key={i}>
              {b && a && (r.kind === 'modified') && (
                <line x1={b[0]} y1={b[1]} x2={a[0]} y2={a[1]} stroke="#9aa0ac" strokeWidth="1.2" strokeDasharray="3 2" />
              )}
              {b && r.kind !== 'added' && <circle cx={b[0]} cy={b[1]} r="4" fill="none" stroke="#9aa0ac" strokeWidth="1.5" />}
              {(a || b) && (() => { const pt = a || b; return (
                <>
                  <circle cx={pt[0]} cy={pt[1]} r="5.5" fill={color} stroke="#fff" strokeWidth="1.5" />
                  {r.kind === 'removed' && <text x={pt[0]} y={pt[1] + 3} textAnchor="middle" fontSize="8" fill="#fff">×</text>}
                  <text x={pt[0] + 8} y={pt[1] + 3} fontSize="10" fill="#374151">{r.geo.name}</text>
                </>
              ) })()}
            </g>
          )
        })}
      </svg>
      <button className="minimap-expand" onClick={(e) => { e.stopPropagation(); onExpand() }}>⤢ Expand</button>
    </div>
  )
}

function FieldTable({ records }) {
  const rows = []
  for (const r of records) for (const f of r.fields || [])
    rows.push({ entity: `${r.table.replace('.txt', '')} ${r.entity}`, ...f })
  if (!rows.length) return null
  return (
    <table className="changetable">
      <thead><tr><th>entity</th><th>field</th><th>before</th><th></th><th>after</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td>{r.entity}</td><td>{r.col}</td>
            <td className="old">{r.before || '∅'}</td><td>→</td><td className="new">{r.after || '∅'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SeqDiff({ rec }) {
  const before = new Map((rec.seq_before || []).map((r) => [r.stop_id, r]))
  const afterIds = new Set((rec.seq_after || []).map((r) => r.stop_id))
  const removed = (rec.seq_before || []).filter((r) => !afterIds.has(r.stop_id))
  return (
    <div className="seqdiff">
      <div className="seqhead">trip {rec.entity}</div>
      <table className="changetable">
        <tbody>
          {(rec.seq_after || []).map((r, i) => {
            const b = before.get(r.stop_id)
            const isNew = !b
            const timeChanged = b && (b.arr !== r.arr || b.dep !== r.dep)
            return (
              <tr key={i} className={isNew ? 'row-new' : ''}>
                <td>{r.seq}</td>
                <td>{r.stop_id}{isNew && <span className="tag new">new</span>}</td>
                <td>{timeChanged ? <><span className="old">{b.arr}</span> → <span className="new">{r.arr}</span></> : r.arr}</td>
              </tr>
            )
          })}
          {removed.map((r, i) => (
            <tr key={'r' + i} className="row-removed"><td>{r.seq}</td><td>{r.stop_id}<span className="tag removed">removed</span></td><td>{r.arr}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FreqTable({ records }) {
  return (
    <table className="changetable">
      <thead><tr><th>trip</th><th>window</th><th>headway before</th><th></th><th>after</th></tr></thead>
      <tbody>
        {records.flatMap((r) => {
          const before = new Map((r.rows_before || []).map((x) => [x.start, x]))
          return (r.rows_after || []).map((x, i) => {
            const b = before.get(x.start)
            if (b && b.headway === x.headway) return null
            return (
              <tr key={r.entity + i}>
                <td>{r.entity}</td><td>{x.start}–{x.end}</td>
                <td className="old">{b?.headway ?? '∅'}</td><td>→</td><td className="new">{x.headway}</td>
              </tr>
            )
          }).filter(Boolean)
        })}
      </tbody>
    </table>
  )
}

function EntityList({ records }) {
  return (
    <div className="entitylist">
      {records.map((r, i) => {
        const noun = r.table.replace('.txt', '')
        const fields = (r.fields || []).filter((f) => (r.kind === 'added' ? f.after : f.before))
        return (
          <div key={i} className={`entrow ${r.kind}`}>
            <span className="entmark">{r.kind === 'added' ? '+' : '−'}</span>
            <span className="entname">{r.kind} {noun} <b>{r.entity}</b></span>
            {fields.length > 0 && (
              <span className="entfields">
                {fields.slice(0, 6).map((f) => `${f.col}=${r.kind === 'added' ? f.after : f.before}`).join(' · ')}
              </span>
            )}
          </div>
        )
      })}
    </div>
  )
}

function aggregate(totals) {
  const parts = []
  for (const [table, kinds] of Object.entries(totals || {})) {
    for (const [kind, n] of Object.entries(kinds)) {
      parts.push(`${n} ${table.replace('.txt', '')} ${kind}`)
    }
  }
  return parts.join(' · ')
}

export default function TurnChanges({ diff, feed }) {
  const [expanded, setExpanded] = useState(false)
  if (!diff || !diff.records) return null
  const recs = diff.records
  const geoRecords = recs.filter((r) => r.geo && (r.geo.before || r.geo.after))
  const fieldRecords = recs.filter((r) => r.fields?.length && r.kind === 'modified')
  // added/removed non-spatial entities (routes, trips, calendars) — no map to show them on
  const addedRemoved = recs.filter((r) => (r.kind === 'added' || r.kind === 'removed') &&
    !(r.geo && (r.geo.before || r.geo.after)) && !r.seq_after && !r.seq_before)
  const seqRecords = recs.filter((r) => r.seq_after || r.seq_before)
  const freqRecords = recs.filter((r) => r.rows_after || r.rows_before)

  return (
    <div className="turnchanges">
      <MiniMap geoRecords={geoRecords} seqRecords={seqRecords} feed={feed} onExpand={() => setExpanded(true)} />
      {addedRemoved.length > 0 && <EntityList records={addedRemoved} />}
      {fieldRecords.length > 0 && <FieldTable records={fieldRecords} />}
      {freqRecords.length > 0 && <FreqTable records={freqRecords} />}
      {seqRecords.slice(0, 3).map((r, i) => <SeqDiff key={i} rec={r} />)}
      {(diff.extra > 0 || seqRecords.length > 3) && (
        <div className="agg">+ {diff.extra + Math.max(0, seqRecords.length - 3)} more · {aggregate(diff.totals)}</div>
      )}
      {expanded && <ExpandedMap geoRecords={geoRecords} seqRecords={seqRecords} feed={feed} onClose={() => setExpanded(false)} />}
    </div>
  )
}
