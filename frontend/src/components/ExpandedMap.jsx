import { useEffect, useRef } from 'react'
import maplibregl from 'maplibre-gl'

// Full-basemap enlarged view of a turn's changed stops (before/after), opened
// from the inline mini-map. MapLibre lives only while the modal is open.
const STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const FONT = ['Noto Sans Regular']

const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null }
const pt = (c, p) => ({ type: 'Feature', properties: p, geometry: { type: 'Point', coordinates: c } })
const ln = (cs) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: cs } })
const fc = (f) => ({ type: 'FeatureCollection', features: f })

function stopLookup(feed) {
  const m = {}
  for (const s of feed?.tables?.['stops.txt']?.rows || []) {
    const lon = num(s.stop_lon), lat = num(s.stop_lat)
    if (lon !== null && lat !== null) m[s.stop_id] = { c: [lon, lat], name: s.stop_name || s.stop_id }
  }
  return m
}

export default function ExpandedMap({ geoRecords, seqRecords, feed, onClose }) {
  const ref = useRef(null)

  useEffect(() => {
    const map = new maplibregl.Map({ container: ref.current, style: STYLE, center: [-116.79, 36.88], zoom: 9 })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    map.on('load', () => { map.resize(); render(map) })
    return () => map.remove()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function render(map) {
    // faint context: every stop in the feed
    const ctx = (feed?.tables?.['stops.txt']?.rows || [])
      .map((s) => [num(s.stop_lon), num(s.stop_lat)])
      .filter((c) => c[0] !== null && c[1] !== null)
      .map((c) => pt(c, {}))
    map.addSource('ctx', { type: 'geojson', data: fc(ctx) })
    map.addLayer({ id: 'ctx', type: 'circle', source: 'ctx',
      paint: { 'circle-radius': 4, 'circle-color': '#c7cbd4', 'circle-stroke-width': 1, 'circle-stroke-color': '#fff' } })

    const after = [], before = [], lines = [], coords = []
    for (const r of geoRecords) {
      const color = r.kind === 'added' ? '#059669' : r.kind === 'removed' ? '#dc2626' : '#2563eb'
      if (r.geo.after) { after.push(pt(r.geo.after, { color, name: r.geo.name })); coords.push(r.geo.after) }
      if (r.geo.before && r.kind !== 'added') { before.push(pt(r.geo.before, {})); coords.push(r.geo.before) }
      if (r.geo.before && r.geo.after && r.kind === 'modified') lines.push(ln([r.geo.before, r.geo.after]))
    }

    // trip paths from stop_times sequences, resolving existing stop coordinates
    const look = stopLookup(feed)
    const tripLines = []
    for (const r of seqRecords || []) {
      const beforeIds = new Set((r.seq_before || []).map((x) => x.stop_id))
      const line = []
      for (const st of r.seq_after || []) {
        const e = look[st.stop_id]
        if (!e) continue
        line.push(e.c); coords.push(e.c)
        after.push(pt(e.c, { color: beforeIds.has(st.stop_id) ? '#2563eb' : '#059669', name: e.name }))
      }
      if (line.length > 1) tripLines.push(ln(line))
    }
    map.addSource('trips', { type: 'geojson', data: fc(tripLines) })
    map.addLayer({ id: 'trips', type: 'line', source: 'trips',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': '#4f46e5', 'line-width': 3, 'line-opacity': 0.7 } })
    map.addSource('lines', { type: 'geojson', data: fc(lines) })
    map.addLayer({ id: 'lines', type: 'line', source: 'lines',
      paint: { 'line-color': '#9aa0ac', 'line-width': 2, 'line-dasharray': [2, 2] } })
    map.addSource('before', { type: 'geojson', data: fc(before) })
    map.addLayer({ id: 'before', type: 'circle', source: 'before',
      paint: { 'circle-radius': 7, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': '#9aa0ac', 'circle-stroke-width': 2 } })
    map.addSource('after', { type: 'geojson', data: fc(after) })
    map.addLayer({ id: 'after', type: 'circle', source: 'after',
      paint: { 'circle-radius': 8, 'circle-color': ['get', 'color'], 'circle-stroke-color': '#fff', 'circle-stroke-width': 2 } })
    map.addLayer({ id: 'after-label', type: 'symbol', source: 'after',
      layout: { 'text-field': ['get', 'name'], 'text-font': FONT, 'text-size': 13, 'text-offset': [0, 1.4], 'text-anchor': 'top' },
      paint: { 'text-color': '#111827', 'text-halo-color': '#fff', 'text-halo-width': 2 } })

    if (coords.length) {
      try {
        const b = coords.reduce((a, c) => a.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]))
        map.fitBounds(b, { padding: 120, maxZoom: 16, duration: 0 })
      } catch { /* degenerate bounds */ }
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <span>Changed stops</span>
          <div className="modal-legend">
            <span><i className="dot" style={{ background: '#059669' }} />added</span>
            <span><i className="dot" style={{ background: '#dc2626' }} />removed</span>
            <span><i className="dot" style={{ background: '#2563eb' }} />moved</span>
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-map" ref={ref} />
      </div>
    </div>
  )
}
