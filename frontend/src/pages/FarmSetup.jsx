// Paste contents from the generated FarmSetup.jsx here
// src/pages/FarmSetup.jsx
/**
 * FarmSetup — draws a polygon on a Leaflet map and registers a farm.
 *
 * This is the most important page: farmers draw their field boundaries
 * using leaflet-draw, and the resulting GeoJSON is sent to the backend
 * which computes centroid, area_ha, and nearest district server-side.
 *
 * Flow:
 *   1. Map initialises centred on Western UP
 *   2. DrawControl appears with Polygon tool active
 *   3. Farmer draws polygon → coordinates shown in sidebar
 *   4. Farmer fills name + crop
 *   5. Submit → POST /farms → redirect to /dashboard
 *
 * Leaflet + leaflet-draw are loaded from CDN via index.html script tags,
 * so they're available on window.L and window.L.Control.Draw.
 */
import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { farmsApi, getToken } from '../api/client'
import { useFarm } from '../App'

// Western UP district centroids for the "jump to district" feature
const DISTRICTS = {
  Baghpat:       [28.94, 77.22],
  Shamli:        [29.45, 77.31],
  Meerut:        [28.98, 77.70],
  Muzaffarnagar: [29.47, 77.68],
  Ghaziabad:     [28.66, 77.42],
}

export default function FarmSetup() {
  const navigate   = useNavigate()
  const { setFarms, setActiveFarmId } = useFarm()

  const mapRef        = useRef(null)
  const mapInstance   = useRef(null)
  const drawnItems    = useRef(null)

  const [polygon,     setPolygon]     = useState(null)   // GeoJSON Geometry
  const [areaHa,      setAreaHa]      = useState(null)   // computed preview
  const [name,        setName]        = useState('')
  const [crop,        setCrop]        = useState('Wheat')
  const [district,    setDistrict]    = useState('Meerut')
  const [step,        setStep]        = useState(1)       // 1=draw, 2=details, 3=done
  const [saving,      setSaving]      = useState(false)
  const [error,       setError]       = useState('')

  // ── Initialise map ──────────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return
    const L = window.L
    if (!L || !L.Control?.Draw) {
      setError('Map library failed to load. Please refresh the page.')
      return
    }

    const map = L.map(mapRef.current, {
      center:   [28.98, 77.70],
      zoom:     12,
      zoomControl: true,
    })
    mapInstance.current = map

    // Satellite-hybrid tile (Esri)
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles © Esri', maxZoom: 19 }
    ).addTo(map)

    // OSM labels overlay
    L.tileLayer(
      'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
      { attribution: '© OSM', opacity: 0.35, maxZoom: 19 }
    ).addTo(map)

    // District centroid markers
    Object.entries(DISTRICTS).forEach(([name, latlng]) => {
      L.circleMarker(latlng, {
        radius: 5, color: '#D4A53F', weight: 2,
        fillColor: '#D4A53F', fillOpacity: 0.8,
      })
        .bindTooltip(name, { permanent: false, direction: 'top' })
        .addTo(map)
    })

    // Layer for drawn shapes
    const drawn = new L.FeatureGroup()
    drawnItems.current = drawn
    map.addLayer(drawn)

    // Draw control — polygon only
    const drawControl = new L.Control.Draw({
      draw: {
        polygon: {
          allowIntersection: false,
          showArea: true,
          metric: true,
          shapeOptions: {
            color:       '#1D9E75',
            weight:      2.5,
            fillColor:   '#1D9E75',
            fillOpacity: 0.2,
          },
        },
        polyline:  false,
        rectangle: false,
        circle:    false,
        marker:    false,
        circlemarker: false,
      },
      edit: { featureGroup: drawn },
    })
    map.addControl(drawControl)

    // ── Draw events ──────────────────────────────────────────────────────────
    map.on(L.Draw.Event.CREATED, (e) => {
      drawn.clearLayers()
      drawn.addLayer(e.layer)

      const geojson = e.layer.toGeoJSON().geometry
      setPolygon(geojson)

      // Compute area preview using Leaflet's geodesic area
      const latlngs = e.layer.getLatLngs()[0]
      const area    = L.GeometryUtil
        ? L.GeometryUtil.geodesicArea(latlngs) / 10000
        : null
      if (area) setAreaHa(area.toFixed(3))

      setStep(2)
    })

    map.on(L.Draw.Event.EDITED, (e) => {
      e.layers.eachLayer(layer => {
        setPolygon(layer.toGeoJSON().geometry)
        const latlngs = layer.getLatLngs()[0]
        const area    = L.GeometryUtil
          ? L.GeometryUtil.geodesicArea(latlngs) / 10000
          : null
        if (area) setAreaHa(area.toFixed(3))
      })
    })

    map.on(L.Draw.Event.DELETED, () => {
      setPolygon(null)
      setAreaHa(null)
      setStep(1)
    })

    return () => { map.remove(); mapInstance.current = null }
  }, [])

  // ── Jump to district ────────────────────────────────────────────────────────
  function jumpToDistrict(name) {
    setDistrict(name)
    const L = window.L
    if (mapInstance.current && L) {
      mapInstance.current.flyTo(DISTRICTS[name], 13, { duration: 1 })
    }
  }

  // ── Clear polygon ───────────────────────────────────────────────────────────
  function clearPolygon() {
    drawnItems.current?.clearLayers()
    setPolygon(null)
    setAreaHa(null)
    setStep(1)
  }

  // ── Submit ──────────────────────────────────────────────────────────────────
  async function handleSubmit(e) {
    e.preventDefault()
    if (!polygon) { setError('Please draw your farm boundary on the map.'); return }
    if (!name.trim()) { setError('Please enter a farm name.'); return }

    setSaving(true)
    setError('')
    try {
      const res = await farmsApi.create({
        name:             name.trim(),
        crop,
        boundary_geojson: polygon,
      })
      const newFarm = res.data

      // Refresh farm list in context
      const listRes = await farmsApi.list()
      setFarms(listRes.data.farms)
      setActiveFarmId(newFarm.id)

      setStep(3)
      setTimeout(() => navigate('/dashboard'), 1800)
    } catch (err) {
      setError(
        err.response?.data?.detail
          || 'Failed to register farm. Please try again.'
      )
    } finally {
      setSaving(false)
    }
  }

  // ── Not logged in ───────────────────────────────────────────────────────────
  if (!getToken()) {
    return (
      <div style={{ minHeight: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Link to="/login" className="btn btn-primary">Sign in first</Link>
      </div>
    )
  }

  // ── Step 3: Success ─────────────────────────────────────────────────────────
  if (step === 3) {
    return (
      <div style={{
        minHeight: '100dvh',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: 'var(--paper)',
        gap: 16,
      }}>
        <div style={{ fontSize: 64, animation: 'pageIn 0.4s ease-out' }}>🌾</div>
        <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 26, color: 'var(--green)', margin: 0 }}>
          Farm Registered!
        </h2>
        <p style={{ color: 'var(--text-muted)', fontSize: 15 }}>
          Redirecting to your dashboard…
        </p>
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100dvh',
      background: 'var(--paper)',
      display: 'grid',
      gridTemplateColumns: '1fr 380px',
      gridTemplateRows: '100dvh',
    }}
    className="farm-setup-grid"
    >
      {/* ── Left: Map ─────────────────────────────────────────────────────── */}
      <div style={{ position: 'relative', overflow: 'hidden' }}>
        {/* Top bar */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, zIndex: 1000,
          background: 'rgba(45,31,20,0.92)',
          backdropFilter: 'blur(8px)',
          padding: '12px 20px',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <Link to="/dashboard" style={{ color: 'rgba(255,255,255,0.6)', textDecoration: 'none', fontSize: 13 }}>
            ← Back
          </Link>
          <div style={{ color: 'rgba(255,255,255,0.3)', fontSize: 18 }}>|</div>
          <span style={{
            fontFamily: 'var(--font-display)', fontWeight: 700,
            color: 'var(--wheat)', fontSize: 16,
          }}>
            🌾 ELISA — Register Farm
          </span>
          <div style={{ flex: 1 }} />
          {/* District jump buttons */}
          <div style={{ display: 'flex', gap: 6 }}>
            {Object.keys(DISTRICTS).map(d => (
              <button
                key={d}
                onClick={() => jumpToDistrict(d)}
                style={{
                  padding: '4px 10px',
                  borderRadius: 'var(--radius-sm)',
                  background: district === d ? 'var(--wheat)' : 'rgba(255,255,255,0.12)',
                  color: district === d ? 'var(--soil)' : 'rgba(255,255,255,0.7)',
                  border: 'none', cursor: 'pointer',
                  fontSize: 12, fontWeight: 600,
                  fontFamily: 'var(--font-mono)',
                  transition: 'all 0.15s',
                }}
              >
                {d}
              </button>
            ))}
          </div>
        </div>

        {/* Map */}
        <div ref={mapRef} style={{ width: '100%', height: '100%' }} />

        {/* Draw instruction overlay */}
        {step === 1 && (
          <div style={{
            position: 'absolute', bottom: 32, left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1000,
            background: 'rgba(45,31,20,0.90)',
            backdropFilter: 'blur(6px)',
            color: '#fff',
            padding: '14px 24px',
            borderRadius: 'var(--radius-lg)',
            fontSize: 14,
            fontFamily: 'var(--font-body)',
            textAlign: 'center',
            boxShadow: 'var(--shadow-xl)',
            border: '1px solid rgba(255,255,255,0.12)',
            pointerEvents: 'none',
          }}>
            <div style={{ fontSize: 20, marginBottom: 6 }}>✏️</div>
            Click the <strong style={{ color: 'var(--wheat)' }}>polygon tool</strong> in the top-left,
            then click your field corners.<br />
            <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.55)' }}>
              Double-click to finish drawing.
            </span>
          </div>
        )}

        {/* Area badge when polygon is drawn */}
        {step === 2 && areaHa && (
          <div style={{
            position: 'absolute', bottom: 32, left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 1000,
            background: 'var(--green)',
            color: '#fff',
            padding: '10px 20px',
            borderRadius: 'var(--radius-lg)',
            fontSize: 14,
            fontFamily: 'var(--font-mono)',
            boxShadow: 'var(--shadow-lg)',
            display: 'flex', alignItems: 'center', gap: 10,
          }}>
            <span>✓ Polygon drawn</span>
            <span style={{ opacity: 0.7 }}>|</span>
            <span>≈ {areaHa} ha</span>
            <button
              onClick={clearPolygon}
              style={{
                background: 'rgba(255,255,255,0.2)', border: 'none',
                color: '#fff', borderRadius: 'var(--radius-sm)',
                padding: '2px 8px', cursor: 'pointer', fontSize: 12,
              }}
            >
              Redraw
            </button>
          </div>
        )}
      </div>

      {/* ── Right: Form panel ─────────────────────────────────────────────── */}
      <div style={{
        background: '#fff',
        borderLeft: '1px solid var(--mist)',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'auto',
      }}>
        {/* Panel header */}
        <div style={{
          background: 'var(--soil)',
          padding: '28px 28px 24px',
        }}>
          <div style={{
            fontSize: 11, fontFamily: 'var(--font-mono)',
            color: 'rgba(255,255,255,0.4)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
            marginBottom: 8,
          }}>
            Step {step} of 2
          </div>
          <h2 style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22, fontWeight: 800,
            color: '#fff', margin: 0,
          }}>
            {step === 1 ? 'Draw your field' : 'Name your farm'}
          </h2>
          <p style={{ color: 'rgba(255,255,255,0.55)', fontSize: 13, margin: '6px 0 0' }}>
            {step === 1
              ? 'Use the polygon tool on the map to trace your field boundary.'
              : 'Fill in the details below and register.'}
          </p>
        </div>

        {/* Progress bar */}
        <div style={{ height: 3, background: 'var(--mist)' }}>
          <div style={{
            height: '100%',
            width: step === 1 ? '33%' : '66%',
            background: 'var(--green)',
            transition: 'width 0.4s ease',
          }} />
        </div>

        {/* Form body */}
        <form onSubmit={handleSubmit} style={{ flex: 1, padding: '28px', display: 'flex', flexDirection: 'column', gap: 0 }}>

          {/* Polygon status */}
          <div style={{
            marginBottom: 24,
            padding: '14px 18px',
            borderRadius: 'var(--radius-md)',
            background: polygon ? 'var(--green-light)' : 'var(--mist)',
            border: `1px solid ${polygon ? 'rgba(29,158,117,0.2)' : 'transparent'}`,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}>
            <div style={{ fontSize: 22 }}>{polygon ? '✅' : '🗺'}</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: polygon ? 'var(--green-dark)' : 'var(--text-muted)' }}>
                {polygon ? 'Boundary drawn' : 'No boundary yet'}
              </div>
              {areaHa && (
                <div style={{ fontSize: 12, color: 'var(--green-dark)', fontFamily: 'var(--font-mono)' }}>
                  ≈ {areaHa} hectares
                </div>
              )}
              {!polygon && (
                <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
                  Draw a polygon on the map first
                </div>
              )}
            </div>
          </div>

          {/* Name */}
          <div className="form-group">
            <label className="form-label">Farm Name</label>
            <input
              className="form-input"
              type="text"
              placeholder="e.g. Ramesh ka khet"
              value={name}
              onChange={e => setName(e.target.value)}
              maxLength={100}
              required
            />
          </div>

          {/* Crop */}
          <div className="form-group">
            <label className="form-label">Primary Crop</label>
            <select
              className="form-input form-select"
              value={crop}
              onChange={e => setCrop(e.target.value)}
            >
              <option value="Wheat">🌾 Wheat (Rabi)</option>
              <option value="Rice">🌿 Rice (Kharif)</option>
            </select>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 5 }}>
              {crop === 'Wheat'
                ? 'Wheat season: Nov – Apr. Irrigation trigger: MAD-based.'
                : 'Rice season: Jun – Oct. Irrigation: ponding method.'}
            </div>
          </div>

          {/* District (read-only, auto-detected) */}
          <div className="form-group">
            <label className="form-label">District (auto-detected from polygon)</label>
            <div style={{
              padding: '10px 14px',
              background: 'var(--mist)',
              borderRadius: 'var(--radius-md)',
              fontSize: 14, fontWeight: 600,
              color: 'var(--text-main)',
              fontFamily: 'var(--font-mono)',
              border: '1.5px solid var(--mist)',
            }}>
              {district}
              <span style={{ fontWeight: 400, fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
                (computed server-side from centroid)
              </span>
            </div>
          </div>

          {/* Agronomy preview */}
          {polygon && (
            <div style={{
              background: 'var(--paper)',
              border: '1px solid var(--mist)',
              borderRadius: 'var(--radius-md)',
              padding: '14px 16px',
              marginBottom: 20,
            }}>
              <div style={{
                fontSize: 11, fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)', textTransform: 'uppercase',
                letterSpacing: '0.07em', marginBottom: 10,
              }}>
                Agronomy Parameters (from YAML)
              </div>
              {crop === 'Wheat' ? (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 20px', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Root depth</span>
                  <span>900 mm</span>
                  <span style={{ color: 'var(--text-muted)' }}>Field capacity</span>
                  <span>225 mm</span>
                  <span style={{ color: 'var(--text-muted)' }}>Trigger (MAD=50%)</span>
                  <span style={{ color: 'var(--alert)' }}>170 mm</span>
                  <span style={{ color: 'var(--text-muted)' }}>Irrigation dose</span>
                  <span>70 mm/event</span>
                </div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 20px', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Ponding target</span>
                  <span>50 mm</span>
                  <span style={{ color: 'var(--text-muted)' }}>Ponding trigger</span>
                  <span style={{ color: 'var(--alert)' }}>20 mm</span>
                  <span style={{ color: 'var(--text-muted)' }}>Percolation</span>
                  <span>5 mm/day</span>
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="alert-banner alert-banner-alert" style={{ marginBottom: 16 }}>
              <span>⚠</span> {error}
            </div>
          )}

          <div style={{ flex: 1 }} />

          {/* Submit */}
          <button
            type="submit"
            className="btn btn-primary btn-lg"
            disabled={!polygon || !name.trim() || saving}
            style={{ width: '100%', marginTop: 8 }}
          >
            {saving
              ? <><span className="spinner" /> Registering…</>
              : 'Register Farm →'}
          </button>

          <div style={{
            marginTop: 12,
            textAlign: 'center',
            fontSize: 12,
            color: 'var(--text-faint)',
          }}>
            Centroid, area, and district are computed server-side from your polygon.
          </div>
        </form>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .farm-setup-grid {
            grid-template-columns: 1fr !important;
            grid-template-rows: 55dvh auto !important;
          }
        }
      `}</style>
    </div>
  )
}