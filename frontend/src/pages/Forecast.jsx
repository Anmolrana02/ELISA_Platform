// Paste contents from the generated Forecast.jsx here
// src/pages/Forecast.jsx
import { useQuery } from '@tanstack/react-query'
import { predictApi, weatherApi } from '../api/client'
import { useFarm } from '../App'
import SMChart from '../components/SMChart'

const CROP_PARAMS = {
  Wheat: { triggerMM: 180, fcMM: 225, pwpMM: 135 },
  Rice:  { triggerMM: 20,  fcMM: 50,  pwpMM: 0 },
}

const WMO_CODES = {
  0:'Clear', 1:'Mainly clear', 2:'Partly cloudy', 3:'Overcast',
  45:'Fog', 51:'Light drizzle', 53:'Drizzle', 61:'Slight rain',
  63:'Moderate rain', 65:'Heavy rain', 80:'Rain showers',
  95:'Thunderstorm', 99:'Thunderstorm+hail',
}

function WeatherCode({ code }) {
  const emojis = {
    0:'☀️', 1:'🌤', 2:'⛅', 3:'☁️', 45:'🌫', 51:'🌦', 53:'🌦',
    61:'🌧', 63:'🌧', 65:'🌧', 80:'🌦', 95:'⛈', 99:'⛈',
  }
  return <span title={WMO_CODES[code]}>{emojis[code] || '🌡'}</span>
}

export default function Forecast() {
  const { farm } = useFarm()

  const { data: predData, isLoading: predLoading, refetch } = useQuery({
    queryKey: ['prediction', farm?.id],
    queryFn:  () => predictApi.get(farm.id).then(r => r.data),
    enabled:  !!farm?.id,
  })

  const { data: wxData, isLoading: wxLoading } = useQuery({
    queryKey: ['weather', farm?.id],
    queryFn:  () => weatherApi.get(farm.id).then(r => r.data),
    enabled:  !!farm?.id,
  })

  if (!farm) return (
    <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
      No farm selected.
    </div>
  )

  const crop     = farm.crop || 'Wheat'
  const params   = CROP_PARAMS[crop] || CROP_PARAMS.Wheat
  const forecast = predData?.sm_forecast || []
  const daily    = wxData?.daily || []
  const rain48h  = wxData?.rain_48h || []

  // Build daily rain totals from daily weather (7 values)
  const rainDaily = daily.map(d => d.precipitation_mm || 0)

  // Status color per day
  function smStatus(sm) {
    if (sm < params.pwpMM)     return { label: '🔴 Stress',  color: 'var(--alert)' }
    if (sm < params.triggerMM) return { label: '⚠️ Low',    color: '#EF9F27' }
    return                            { label: '✅ Safe',    color: 'var(--green)' }
  }

  const today = new Date()

  return (
    <div className="page-enter">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">📈 7-Day Forecast</h1>
          <p className="page-subtitle">{farm.name} · {farm.district} · {crop}</p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => refetch()}
        >
          ↺ Refresh
        </button>
      </div>

      {/* Chart */}
      <div className="card" style={{ marginBottom: 20, padding: '20px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div className="card-title" style={{ margin: 0 }}>Soil Moisture + Rain Forecast</div>
          <div style={{ display: 'flex', gap: 12, fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--alert)' }}>── Trigger {params.triggerMM}mm</span>
            <span style={{ color: 'var(--green)' }}>── FC {params.fcMM}mm</span>
          </div>
        </div>
        <SMChart
          smForecast  = {forecast}
          rainDaily   = {rainDaily}
          currentSM   = {predData?.sm_forecast?.[0]}
          triggerMM   = {params.triggerMM}
          fcMM        = {params.fcMM}
          pwpMM       = {params.pwpMM}
          loading     = {predLoading}
          height      = {300}
        />
        <div style={{
          marginTop: 12,
          fontSize: 11, fontFamily: 'var(--font-mono)',
          color: 'var(--text-faint)', textAlign: 'right',
        }}>
          ★ = observed today | Days 1–7 = PatchTST prediction | Rain bars = OpenMeteo
          {predData?.from_cache && ' | cached'}
        </div>
      </div>

      {/* Daily table */}
      <div className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
        <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--mist)' }}>
          <div className="card-title" style={{ margin: 0 }}>Daily Breakdown</div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'var(--paper)', borderBottom: '1px solid var(--mist)' }}>
                {['Day', 'Date', 'SM Forecast', 'Status', 'Rain', 'Temp Max', 'ETo', 'Wx'].map(h => (
                  <th key={h} style={{
                    padding: '10px 16px', textAlign: 'left',
                    fontSize: 11, fontFamily: 'var(--font-mono)',
                    color: 'var(--text-muted)', textTransform: 'uppercase',
                    letterSpacing: '0.06em', whiteSpace: 'nowrap',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 7 }).map((_, i) => {
                const d = new Date(today); d.setDate(d.getDate() + i + 1)
                const sm   = forecast[i]
                const wx   = daily[i]
                const rain = rainDaily[i]
                const st   = sm !== undefined ? smStatus(sm) : null
                return (
                  <tr
                    key={i}
                    style={{
                      borderBottom: '1px solid var(--mist)',
                      background: i % 2 === 0 ? '#fff' : 'rgba(245,240,232,0.3)',
                    }}
                  >
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-muted)' }}>
                      Day {i+1}
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
                      {d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      {predLoading
                        ? <div className="skeleton" style={{ height: 16, width: 60 }} />
                        : sm !== undefined
                          ? <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: st?.color }}>
                              {sm.toFixed(1)} mm
                            </span>
                          : <span style={{ color: 'var(--text-faint)' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      {st
                        ? <span className="badge" style={{
                            background: `${st.color}18`,
                            color: st.color,
                            fontFamily: 'var(--font-mono)',
                          }}>
                            {st.label}
                          </span>
                        : <span style={{ color: 'var(--text-faint)' }}>—</span>
                      }
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)' }}>
                      {wxLoading
                        ? '…'
                        : rain > 0
                          ? <span style={{ color: 'var(--sky)' }}>{rain.toFixed(1)} mm</span>
                          : <span style={{ color: 'var(--text-faint)' }}>0.0 mm</span>
                      }
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)' }}>
                      {wx?.temp_max_c != null ? `${wx.temp_max_c.toFixed(0)}°C` : '—'}
                    </td>
                    <td style={{ padding: '12px 16px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                      {wx?.et0_mm != null ? `${wx.et0_mm.toFixed(1)} mm` : '—'}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: 18 }}>
                      {wx?.weather_code != null ? <WeatherCode code={wx.weather_code} /> : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 48h rain detail */}
      {rain48h.length > 0 && (
        <div className="card">
          <div className="card-title">48-Hour Rain Detail (OpenMeteo)</div>
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 48, marginTop: 8 }}>
            {rain48h.slice(0, 48).map((r, i) => (
              <div
                key={i}
                title={`Hour ${i}: ${r.toFixed(1)}mm`}
                style={{
                  flex: 1,
                  height: r > 0 ? `${Math.min(100, r * 20 + 5)}%` : '4%',
                  background: r > 0 ? 'var(--sky)' : 'var(--mist)',
                  borderRadius: '2px 2px 0 0',
                  minHeight: 3,
                  transition: 'height 0.3s',
                }}
              />
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: 4 }}>
            <span>Now</span><span>+12h</span><span>+24h</span><span>+36h</span><span>+48h</span>
          </div>
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
            24h total: <strong style={{ color: 'var(--sky)' }}>{wxData?.rain_24h_total_mm?.toFixed(1)} mm</strong>
            {wxData?.rain_24h_total_mm > 5 && (
              <span style={{ color: 'var(--green)', marginLeft: 12 }}>
                🌧 Rain suppression threshold exceeded (5mm)
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}