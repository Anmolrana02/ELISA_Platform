// Paste contents from the generated FarmMap.jsx here
// src/components/FarmMap.jsx
/**
 * FarmMap — displays a farm's boundary polygon on a Leaflet map.
 *
 * Props:
 *   farm        object  — farm object with boundary_geojson, centroid_lat/lon
 *   farms       array   — optional: all farms (shows multi-farm overview)
 *   height      number  — map height in px
 *   interactive bool    — whether to show zoom controls
 */
import { useEffect, useRef } from 'react'

export default function FarmMap({
  farm,
  farms,
  height = 260,
  interactive = false,
}) {
  const mapRef      = useRef(null)
  const instanceRef = useRef(null)

  useEffect(() => {
    if (!mapRef.current) return
    if (instanceRef.current) {
      instanceRef.current.remove()
      instanceRef.current = null
    }

    // Dynamically import Leaflet so it doesn't SSR-crash
    const L = window.L
    if (!L) {
      console.warn('Leaflet not loaded yet')
      return
    }

    const center = farm?.centroid_lat
      ? [farm.centroid_lat, farm.centroid_lon]
      : [28.98, 77.70]  // Meerut default

    const map = L.map(mapRef.current, {
      center,
      zoom:              farm?.boundary_geojson ? 14 : 11,
      zoomControl:       interactive,
      scrollWheelZoom:   interactive,
      dragging:          interactive,
      touchZoom:         interactive,
      doubleClickZoom:   interactive,
      boxZoom:           interactive,
      keyboard:          interactive,
    })

    instanceRef.current = map

    // OSM tiles
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap',
      maxZoom: 19,
    }).addTo(map)

    const bounds = []

    // Render the primary farm polygon
    if (farm?.boundary_geojson) {
      const poly = L.geoJSON(farm.boundary_geojson, {
        style: {
          color:       '#1D9E75',
          weight:      2.5,
          opacity:     0.9,
          fillColor:   '#1D9E75',
          fillOpacity: 0.15,
        },
      }).addTo(map)
      bounds.push(...Object.values(poly.getBounds()))
      if (interactive) map.fitBounds(poly.getBounds(), { padding: [20, 20] })
    }

    // Multi-farm overview dots
    if (farms?.length) {
      farms.forEach(f => {
        if (!f.centroid_lat) return
        const isActive = f.id === farm?.id
        L.circleMarker([f.centroid_lat, f.centroid_lon], {
          radius:      isActive ? 10 : 6,
          color:       isActive ? '#1D9E75' : '#4A9CC4',
          weight:      2,
          fillColor:   isActive ? '#1D9E75' : '#4A9CC4',
          fillOpacity: 0.7,
        })
          .bindTooltip(`<b>${f.name}</b><br/>${f.district} · ${f.crop}`, {
            direction: 'top', offset: [0, -8],
          })
          .addTo(map)
      })
    } else if (farm?.centroid_lat) {
      // Single farm centroid marker
      const icon = L.divIcon({
        html: `<div style="
          background: #1D9E75; color: #fff;
          border-radius: 50%; width: 28px; height: 28px;
          display: flex; align-items: center; justify-content: center;
          font-size: 14px; font-weight: 700;
          border: 2px solid #fff; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
        ">🌾</div>`,
        iconSize:   [28, 28],
        iconAnchor: [14, 14],
        className:  '',
      })
      L.marker([farm.centroid_lat, farm.centroid_lon], { icon })
        .bindTooltip(`<b>${farm.name}</b><br/>${farm.district}`, { direction: 'top' })
        .addTo(map)
    }

    return () => {
      map.remove()
      instanceRef.current = null
    }
  }, [farm?.id, farms?.length, interactive])

  return (
    <div
      ref={mapRef}
      style={{
        height,
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
        background: 'var(--mist)',
      }}
    />
  )
}