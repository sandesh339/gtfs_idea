import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'

const STYLE = 'https://tiles.openfreemap.org/styles/liberty'
// OpenFreeMap serves Noto Sans glyphs; the MapLibre default (Open Sans) 404s.
const FONT = ['Noto Sans Regular']

const num = (v) => {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : null
}

// Distinct colors for routes that don't carry their own route_color.
const PALETTE = ['#e6194B', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4',
  '#f032e6', '#469990', '#9A6324', '#800000', '#808000', '#000075', '#e07a5f',
  '#2a9d8f', '#bc6c25', '#6a4c93']

// route_id -> hex color (feed's route_color if valid, else a palette color)
function routeColors(feed) {
  const routes = feed?.tables?.['routes.txt']?.rows || []
  const map = {}
  routes.forEach((r, i) => {
    const c = (r.route_color || '').trim()
    map[r.route_id] = /^[0-9a-fA-F]{6}$/.test(c) ? `#${c}` : PALETTE[i % PALETTE.length]
  })
  return map
}

// GeoJSON for stops and (from shapes.txt if present) route lines, colored by route.
function buildGeo(feed, changedStops) {
  const stops = feed?.tables?.['stops.txt']?.rows || []
  const stopFeatures = []
  for (const s of stops) {
    const lon = num(s.stop_lon), lat = num(s.stop_lat)
    if (lon === null || lat === null) continue        // skip stops without valid coords
    stopFeatures.push({
      type: 'Feature',
      properties: { id: s.stop_id, name: s.stop_name || s.stop_id,
        changed: changedStops.has(s.stop_id) ? 1 : 0 },
      geometry: { type: 'Point', coordinates: [lon, lat] },
    })
  }

  const colors = routeColors(feed)
  const trips = feed?.tables?.['trips.txt']?.rows || []
  const shapeRoute = {}
  for (const t of trips) {
    if (t.shape_id && !(t.shape_id in shapeRoute)) shapeRoute[t.shape_id] = t.route_id
  }

  const shapes = feed?.tables?.['shapes.txt']?.rows || []
  const byShape = {}
  for (const r of shapes) {
    const lon = num(r.shape_pt_lon), lat = num(r.shape_pt_lat)
    if (lon === null || lat === null) continue
    ;(byShape[r.shape_id] = byShape[r.shape_id] || []).push([lon, lat, num(r.shape_pt_sequence) || 0])
  }
  const lineFeatures = Object.entries(byShape).map(([id, pts]) => ({
    type: 'Feature',
    properties: { id, route_id: shapeRoute[id] || '', color: colors[shapeRoute[id]] || '#7c7c8a' },
    geometry: { type: 'LineString', coordinates: pts.sort((a, b) => a[2] - b[2]).map(([x, y]) => [x, y]) },
  }))

  return {
    stops: { type: 'FeatureCollection', features: stopFeatures },
    lines: { type: 'FeatureCollection', features: lineFeatures },
  }
}

function fitToStops(map, geo) {
  const coords = geo.stops.features.map((f) => f.geometry.coordinates)
  if (!coords.length) return
  try {
    const b = coords.reduce((acc, c) => acc.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]))
    map.fitBounds(b, { padding: 70, maxZoom: 14, duration: 500 })
  } catch { /* ignore degenerate bounds */ }
}

export default function MapView({ feed, changedStops, feedKey }) {
  const ref = useRef(null)
  const mapRef = useRef(null)
  const lastKey = useRef(null)          // which feed we last fit the view to
  const [ready, setReady] = useState(false)
  const changed = changedStops || new Set()

  useEffect(() => {
    const map = new maplibregl.Map({ container: ref.current, style: STYLE, center: [-116.79, 36.88], zoom: 9 })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map
    map.on('load', () => setReady(true))
    return () => { map.remove(); mapRef.current = null }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !feed) return
    const geo = buildGeo(feed, changed)

    const upsert = (id, data, addLayer) => {
      const src = map.getSource(id)
      if (src) src.setData(data)
      else { map.addSource(id, { type: 'geojson', data }); addLayer() }
    }

    upsert('lines', geo.lines, () =>
      map.addLayer({ id: 'route-lines', type: 'line', source: 'lines',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.75 } }))

    upsert('stops', geo.stops, () => {
      map.addLayer({ id: 'stop-points', type: 'circle', source: 'stops',
        paint: {
          'circle-radius': ['case', ['==', ['get', 'changed'], 1], 8, 5],
          'circle-color': ['case', ['==', ['get', 'changed'], 1], '#dc2626', '#2563eb'],
          'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff',
        } })
      map.addLayer({ id: 'stop-labels', type: 'symbol', source: 'stops',
        layout: { 'text-field': ['get', 'name'], 'text-font': FONT, 'text-size': 11,
          'text-offset': [0, 1.2], 'text-anchor': 'top' },
        paint: { 'text-color': '#374151', 'text-halo-color': '#ffffff', 'text-halo-width': 1.5 } })
    })

    // Re-center only when the ACTIVE feed changes (upload / switch), not on edits
    // (edits keep the current zoom and just highlight what changed).
    if (feedKey !== lastKey.current && geo.stops.features.length) {
      fitToStops(map, geo)
      lastKey.current = feedKey
    }
  }, [feed, changedStops, ready, feedKey])

  return (
    <>
      <div className="map" ref={ref} />
      <div className="map-legend">
        <div><span className="dot" style={{ background: '#2563eb' }} />stop</div>
        <div><span className="dot" style={{ background: '#dc2626' }} />changed</div>
        <div>
          <span className="dot" style={{ background: '#e6194B' }} />
          <span className="dot" style={{ background: '#3cb44b' }} />
          <span className="dot" style={{ background: '#4363d8' }} />
          routes (by colour)
        </div>
      </div>
    </>
  )
}
