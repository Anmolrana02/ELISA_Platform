// Paste contents from the generated Decision.jsx here
// src/pages/Decision.jsx
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { predictApi, irrigationApi } from '../api/client'
import { useFarm } from '../App'
import DecisionCard from '../components/DecisionCard'

export default function Decision() {
  const { farm } = useFarm()
  const qc = useQueryClient()

  const [confirming,  setConfirming]  = useState(false)
  const [mmInput,     setMmInput]     = useState(70)
  const [confirmed,   setConfirmed]   = useState(false)
  const [confirmMsg,  setConfirmMsg]  = useState('')
  const [error,       setError]       = useState('')
  const [showLog,     setShowLog]     = useState(false)

  const { data: pred, isLoading: predLoading, refetch } = useQuery({
    queryKey: ['prediction', farm?.id],
    queryFn:  () => predictApi.get(farm.id).then(r => r.data),
    enabled:  !!farm?.id,
  })

  const { data: histData } = useQuery({
    queryKey: ['irr-history', farm?.id],
    queryFn:  () => irrigationApi.history(farm.id, 60).then(r => r.data),
    enabled:  !!farm?.id && showLog,
  })

  async function handleConfirm() {
    if (!farm) return
    setConfirming(true); setError('')
    try {
      const today = new Date().toISOString().split('T')[0]
      const res = await irrigationApi.confirm(farm.id, today, mmInput)
      const d = res.data
      setConfirmed(true)
      setConfirmMsg(
        `Logged ${d.mm} mm. Updated SM: ${d.sm_mm.toFixed(1)} mm. ` +
        `Season water saved: ${d.water_saved_mm} mm / ₹${d.cost_saved_inr} saved.`
      )
      // Invalidate caches so next prediction reflects new SM
      qc.invalidateQueries(['prediction', farm.id])
      qc.invalidateQueries(['pred-history', farm.id])
      qc.invalidateQueries(['savings', farm.id])
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to log irrigation.')
    } finally {
      setConfirming(false)
    }
  }

  if (!farm) return (
    <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
      No farm selected.
    </div>
  )

  return (
    <div className="page-enter">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">🚿 Irrigation Decision</h1>
          <p className="page-subtitle">{farm.name} · 48h MPC optimiser</p>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={() => refetch()}>↺ Refresh</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 20 }}>

        {/* Left: Decision + confirm */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

          <DecisionCard
            prediction={pred}
            loading={predLoading}
            onConfirm={() => {}}     // handled below
            confirming={false}
          />

          {/* Manual confirm panel */}
          <div className="card">
            <div className="card-title">Log an Irrigation Event</div>
            <p style={{ fontSize: 14, color: 'var(--text-muted)', marginBottom: 20 }}>
              When you irrigate, record it here. The model will account for it
              in tomorrow's forecast — this closes the feedback loop.
            </p>

            {confirmed ? (
              <div className="alert-banner alert-banner-green">
                <span style={{ fontSize: 20 }}>✅</span>
                <div>
                  <div style={{ fontWeight: 600 }}>Irrigation logged!</div>
                  <div style={{ fontSize: 13, marginTop: 3 }}>{confirmMsg}</div>
                </div>
              </div>
            ) : (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label">Water Applied (mm)</label>
                    <input
                      className="form-input"
                      type="number"
                      min={10} max={200} step={5}
                      value={mmInput}
                      onChange={e => setMmInput(Number(e.target.value))}
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 18, fontWeight: 600 }}
                    />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label">Date</label>
                    <input
                      className="form-input"
                      type="date"
                      defaultValue={new Date().toISOString().split('T')[0]}
                      style={{ fontFamily: 'var(--font-mono)' }}
                      disabled
                    />
                  </div>
                </div>

                {/* Pump preset buttons */}
                <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
                  {[50, 70, 80, 100].map(v => (
                    <button
                      key={v}
                      className="btn btn-ghost btn-sm"
                      style={{ fontFamily: 'var(--font-mono)', background: mmInput === v ? 'var(--green-light)' : undefined, color: mmInput === v ? 'var(--green-dark)' : undefined }}
                      onClick={() => setMmInput(v)}
                    >
                      {v} mm
                    </button>
                  ))}
                  <span style={{ fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center', marginLeft: 4 }}>
                    Typical: Wheat 70mm · Rice 50mm
                  </span>
                </div>

                {error && (
                  <div className="alert-banner alert-banner-alert" style={{ marginBottom: 16 }}>
                    {error}
                  </div>
                )}

                <button
                  className="btn btn-primary"
                  onClick={handleConfirm}
                  disabled={confirming}
                  style={{ width: '100%' }}
                >
                  {confirming
                    ? <><span className="spinner" /> Logging…</>
                    : `✓ I irrigated ${mmInput} mm today`}
                </button>
              </>
            )}
          </div>

          {/* Irrigation history toggle */}
          <div className="card" style={{ padding: 16 }}>
            <button
              className="btn btn-ghost"
              style={{ width: '100%', justifyContent: 'space-between' }}
              onClick={() => setShowLog(l => !l)}
            >
              <span>📋 Irrigation History</span>
              <span>{showLog ? '▲' : '▼'}</span>
            </button>

            {showLog && (
              <div style={{ marginTop: 16 }}>
                {!histData?.events?.length ? (
                  <div style={{ color: 'var(--text-muted)', fontSize: 14, textAlign: 'center', padding: 16 }}>
                    No irrigation events logged yet.
                  </div>
                ) : (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--mist)' }}>
                        <th style={{ textAlign: 'left', padding: '6px 0', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Date</th>
                        <th style={{ textAlign: 'right', padding: '6px 0', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Amount</th>
                        <th style={{ textAlign: 'right', padding: '6px 0', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {histData.events.map((ev, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--mist)' }}>
                          <td style={{ padding: '8px 0', fontFamily: 'var(--font-mono)' }}>{ev.date}</td>
                          <td style={{ padding: '8px 0', textAlign: 'right', fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--sky)' }}>
                            {ev.irrigation_mm.toFixed(0)} mm
                          </td>
                          <td style={{ padding: '8px 0', textAlign: 'right', fontSize: 11, color: 'var(--text-muted)' }}>
                            {ev.source}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right: MPC logic explainer */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* 3 Conditions */}
          <div className="card">
            <div className="card-title">MPC Logic (3 Conditions)</div>
            {[
              {
                label: 'C1 — SM Forecast',
                desc: '48h SM forecast from PatchTST. If both day-1 and day-2 stay above crop trigger → skip.',
                value: pred?.sm_forecast
                  ? `Day1: ${pred.sm_forecast[0]?.toFixed(0)}mm · Day2: ${pred.sm_forecast[1]?.toFixed(0)}mm`
                  : '—',
                pass: pred && !pred.irrigate,
              },
              {
                label: 'C2 — Rain Suppression',
                desc: 'If >5mm rain forecast in next 24h → skip irrigation.',
                value: pred?.rain_24h_mm != null ? `${pred.rain_24h_mm.toFixed(1)}mm / 24h` : '—',
                pass: pred?.rain_24h_mm > 5,
              },
              {
                label: 'C3 — Tariff Optimisation',
                desc: 'Find cheapest 2-hour pump window using UPPCL ToU tariff schedule.',
                value: pred?.pump_start_hour != null
                  ? `${String(pred.pump_start_hour).padStart(2,'0')}:00–${String(pred.pump_end_hour).padStart(2,'0')}:00 · ₹${pred.cost_inr?.toFixed(2)}`
                  : '—',
                pass: null,
              },
            ].map((c, i) => (
              <div key={i} style={{
                padding: '14px 0',
                borderBottom: i < 2 ? '1px solid var(--mist)' : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-display)' }}>{c.label}</div>
                  {c.pass !== null && (
                    <span className={`badge ${c.pass ? 'badge-green' : 'badge-stone'}`} style={{ fontSize: 10 }}>
                      {c.pass ? '✓ suppressed' : '→ continue'}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>{c.desc}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-main)', fontWeight: 600 }}>{c.value}</div>
              </div>
            ))}
          </div>

          {/* Tariff schedule */}
          <div className="card">
            <div className="card-title">UPPCL Tariff Schedule</div>
            {[
              { slot: '00:00–06:00', rate: '₹3.50', label: 'Low', color: 'var(--green)' },
              { slot: '06:00–18:00', rate: '₹6.00', label: 'Medium', color: '#EF9F27' },
              { slot: '18:00–22:00', rate: '₹9.50', label: 'Peak', color: 'var(--alert)' },
              { slot: '22:00–24:00', rate: '₹6.00', label: 'Medium', color: '#EF9F27' },
            ].map(t => (
              <div key={t.slot} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 0', borderBottom: '1px solid var(--mist)',
                fontSize: 13,
              }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-muted)' }}>{t.slot}</span>
                <span style={{ fontFamily: 'var(--font-display)', fontWeight: 700, color: t.color }}>{t.rate}/kWh</span>
                <span className="badge" style={{ background: `${t.color}18`, color: t.color, fontSize: 10 }}>{t.label}</span>
              </div>
            ))}
            <div style={{ marginTop: 12, fontSize: 12, color: 'var(--text-muted)' }}>
              5HP pump · η=0.65 · 2h run ≈ 11.47 kWh/event<br />
              Best window: <strong>00:00–02:00</strong> = ₹{(11.47 * 3.5).toFixed(2)}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}