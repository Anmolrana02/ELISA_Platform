// Paste contents from the generated Dashboard.jsx here
// src/pages/Dashboard.jsx
import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { farmsApi, predictApi } from '../api/client'
import { useFarm } from '../App'
import MetricCard from '../components/MetricCard'
import FarmMap    from '../components/FarmMap'
import DecisionCard from '../components/DecisionCard'

function NoFarm() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      minHeight: '60vh', gap: 16, textAlign: 'center',
    }}>
      <div style={{ fontSize: 56 }}>🌱</div>
      <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 24 }}>No farms yet</h2>
      <p style={{ color: 'var(--text-muted)', fontSize: 15, maxWidth: 320 }}>
        Register your first farm to get irrigation recommendations.
      </p>
      <Link to="/farms/new" className="btn btn-primary btn-lg">Register a Farm →</Link>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { farm, farms, setFarms, setActiveFarmId } = useFarm()

  // Load farms on mount
  const { data: farmsData } = useQuery({
    queryKey: ['farms'],
    queryFn:  () => farmsApi.list().then(r => r.data),
  })

  useEffect(() => {
    if (farmsData?.farms) {
      setFarms(farmsData.farms)
      if (!farm && farmsData.farms.length > 0) {
        setActiveFarmId(farmsData.farms[0].id)
      }
    }
  }, [farmsData])

  // Today's prediction (from cache most of the time)
  const { data: predData, isLoading: predLoading } = useQuery({
    queryKey:  ['prediction', farm?.id],
    queryFn:   () => predictApi.get(farm.id).then(r => r.data),
    enabled:   !!farm?.id,
    refetchInterval: 1000 * 60 * 30,  // refresh every 30 min
  })

  // Prediction history for SM sparkline (14 days)
  const { data: histData } = useQuery({
    queryKey: ['pred-history', farm?.id],
    queryFn:  () => predictApi.history(farm.id, 14).then(r => r.data),
    enabled:  !!farm?.id,
  })

  if (!farm && farmsData?.total === 0) return <NoFarm />
  if (!farm) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
      <div style={{ textAlign: 'center' }}>
        <div className="skeleton" style={{ height: 200, width: 300, borderRadius: 'var(--radius-lg)', margin: '0 auto 20px' }} />
        <div className="skeleton" style={{ height: 20, width: 200, margin: '0 auto' }} />
      </div>
    </div>
  )

  const pred = predData
  const hist = histData?.predictions || []

  // SM from most recent prediction or current state
  const latestSM = pred?.sm_forecast?.[0] ?? null
  const smColor = !latestSM ? 'default'
    : latestSM < 135 ? 'alert'
    : latestSM < 170 ? 'wheat'
    : 'green'

  // History sparkline data
  const recentSM = hist
    .slice(0, 7)
    .reverse()
    .map(p => p.sm_forecast?.[0])
    .filter(v => v !== undefined && v !== null)

  return (
    <div className="page-enter">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">🌾 {farm.name}</h1>
          <p className="page-subtitle">
            {farm.district} · {farm.crop} ·{' '}
            {farm.area_ha ? `${farm.area_ha.toFixed(2)} ha` : 'area pending'} ·{' '}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>
              {farm.centroid_lat?.toFixed(4)}°N {farm.centroid_lon?.toFixed(4)}°E
            </span>
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Link to="/farms/new" className="btn btn-ghost btn-sm">+ Add farm</Link>
          <Link to="/decision" className="btn btn-primary btn-sm">View decision →</Link>
        </div>
      </div>

      {/* ── Metric row ──────────────────────────────────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 16,
        marginBottom: 24,
      }}>
        <MetricCard
          label="Soil Moisture"
          value={latestSM?.toFixed(0) ?? '—'}
          unit="mm"
          sublabel={farm.crop === 'Wheat' ? 'Trigger: 170 mm · FC: 225 mm' : 'Ponding trigger: 20 mm'}
          variant={smColor}
          loading={predLoading}
        />
        <MetricCard
          label="7-Day Forecast"
          value={pred?.sm_forecast?.[6]?.toFixed(0) ?? '—'}
          unit="mm Day 7"
          sublabel={pred?.irrigate ? '⚠ Irrigation required' : '✓ SM stays adequate'}
          variant={pred?.irrigate ? 'alert' : 'default'}
          loading={predLoading}
        />
        <MetricCard
          label="Pump Window"
          value={
            pred?.pump_start_hour != null
              ? `${String(pred.pump_start_hour).padStart(2,'0')}:00`
              : '—'
          }
          unit={
            pred?.pump_end_hour != null
              ? `– ${String(pred.pump_end_hour).padStart(2,'0')}:00`
              : ''
          }
          sublabel={pred?.cost_inr ? `₹${pred.cost_inr.toFixed(2)} estimated` : 'Cheapest tariff window'}
          variant="wheat"
          loading={predLoading}
        />
        <MetricCard
          label="Rain Forecast"
          value={pred?.rain_24h_mm?.toFixed(1) ?? '0.0'}
          unit="mm/24h"
          sublabel={pred?.rain_24h_mm > 5 ? '🌧 Rain suppression active' : 'No suppression'}
          variant={pred?.rain_24h_mm > 5 ? 'sky' : 'default'}
          loading={predLoading}
        />
      </div>

      {/* ── Main content grid ──────────────────────────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 340px',
        gap: 20,
      }}>
        {/* Left column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Decision card */}
          <DecisionCard
            prediction={pred}
            loading={predLoading}
            onConfirm={() => navigate('/decision')}
          />

          {/* 14-day SM history */}
          <div className="card">
            <div className="card-title">14-Day SM History (Day+1 forecast)</div>
            {hist.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 14, textAlign: 'center', padding: '24px 0' }}>
                No history yet — predictions start at 05:00 IST.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                {hist.slice(0, 10).map((p, i) => {
                  const sm = p.sm_forecast?.[0]
                  const trigger = 170
                  const pct = sm ? Math.min(100, (sm / (trigger * 1.5)) * 100) : 0
                  return (
                    <div key={p.date} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{
                        fontSize: 11, fontFamily: 'var(--font-mono)',
                        color: 'var(--text-muted)', width: 72, flexShrink: 0,
                      }}>
                        {new Date(p.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                      </div>
                      <div style={{ flex: 1, height: 8, background: 'var(--mist)', borderRadius: 99, overflow: 'hidden' }}>
                        <div style={{
                          height: '100%',
                          width: `${pct}%`,
                          background: sm < trigger ? 'var(--alert)' : 'var(--green)',
                          borderRadius: 99,
                          transition: 'width 0.4s ease',
                        }} />
                      </div>
                      <div style={{
                        fontSize: 12, fontFamily: 'var(--font-mono)',
                        fontWeight: 600,
                        color: sm < trigger ? 'var(--alert)' : 'var(--green)',
                        width: 50, textAlign: 'right',
                      }}>
                        {sm?.toFixed(0) ?? '—'} mm
                      </div>
                      {p.irrigate && (
                        <span style={{ fontSize: 11, color: 'var(--alert)' }}>💧</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Farm map */}
          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Farm Location</div>
            <FarmMap farm={farm} farms={farms} height={200} interactive={false} />
            {farm.area_ha && (
              <div style={{
                marginTop: 10,
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
              }}>
                {[
                  ['Area', `${farm.area_ha.toFixed(2)} ha`],
                  ['District', farm.district],
                  ['Crop', farm.crop],
                  ['GEE', farm.gee_extracted ? '✅ Extracted' : '⏳ Pending'],
                ].map(([k, v]) => (
                  <div key={k}>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{k}</div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{v}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick links */}
          <div className="card" style={{ padding: 16 }}>
            <div className="card-title">Quick Actions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              <Link to="/forecast" className="btn btn-ghost" style={{ justifyContent: 'flex-start', width: '100%' }}>
                📈 View 7-day forecast
              </Link>
              <Link to="/decision" className="btn btn-ghost" style={{ justifyContent: 'flex-start', width: '100%' }}>
                🚿 Log irrigation event
              </Link>
              <Link to="/savings" className="btn btn-ghost" style={{ justifyContent: 'flex-start', width: '100%' }}>
                💰 View season savings
              </Link>
            </div>
          </div>

          {/* Method note */}
          <div style={{
            padding: '14px 16px',
            background: 'var(--mist)',
            borderRadius: 'var(--radius-md)',
            fontSize: 12, color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            lineHeight: 1.6,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-main)' }}>Model info</div>
            PatchTST (30-day input, 7-day output)<br />
            48h MPC: C1 SM → C2 rain → C3 tariff<br />
            Scheduler: 05:00 IST daily
          </div>
        </div>
      </div>
    </div>
  )
}