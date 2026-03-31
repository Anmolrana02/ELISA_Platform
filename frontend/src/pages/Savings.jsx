// Paste contents from the generated Savings.jsx here
// src/pages/Savings.jsx
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { savingsApi } from '../api/client'
import { useFarm } from '../App'
import MetricCard from '../components/MetricCard'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, Legend,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#fff', border: '1px solid var(--mist)',
      borderRadius: 'var(--radius-md)', padding: '12px 16px',
      boxShadow: 'var(--shadow-md)', fontFamily: 'var(--font-mono)', fontSize: 13,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 8, color: 'var(--text-muted)' }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.fill, marginBottom: 3 }}>
          {p.name}: <strong>{p.value?.toFixed(1)}</strong>
        </div>
      ))}
    </div>
  )
}

export default function Savings() {
  const { farm } = useFarm()
  const qc = useQueryClient()
  const [recomputing, setRecomputing] = useState(false)

  const { data: savings, isLoading, refetch } = useQuery({
    queryKey: ['savings', farm?.id],
    queryFn:  () => savingsApi.get(farm.id).then(r => r.data),
    enabled:  !!farm?.id,
  })

  const { data: histData } = useQuery({
    queryKey: ['savings-history', farm?.id],
    queryFn:  () => savingsApi.history(farm.id).then(r => r.data),
    enabled:  !!farm?.id,
  })

  async function handleRecompute() {
    setRecomputing(true)
    try {
      await savingsApi.recompute(farm.id)
      qc.invalidateQueries(['savings', farm.id])
      qc.invalidateQueries(['savings-history', farm.id])
      refetch()
    } finally {
      setRecomputing(false)
    }
  }

  if (!farm) return (
    <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
      No farm selected.
    </div>
  )

  const s = savings

  // Bar chart data: actual vs blind for current season
  const comparisonData = s ? [
    { name: 'Water (mm)',  ELISA: s.actual_water_mm,  Blind: s.blind_water_mm },
    { name: 'Cost (₹)',    ELISA: s.actual_cost_inr,  Blind: s.blind_cost_inr },
    { name: 'Events',     ELISA: s.actual_events,     Blind: s.blind_baseline_events },
  ] : []

  // History bar data
  const histChartData = histData?.seasons?.map(s => ({
    season:       s.season,
    water_saved:  s.water_saved_mm,
    cost_saved:   s.cost_saved_inr,
  })) || []

  const savingsPct = s?.savings_pct_water

  return (
    <div className="page-enter">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 className="page-title">💰 Season Savings</h1>
          <p className="page-subtitle">
            {farm.name} · {s?.season || '—'} · vs Blind farmer baseline
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleRecompute}
          disabled={recomputing}
        >
          {recomputing ? <><span className="spinner" style={{ borderTopColor: 'var(--green)' }} /> Computing…</> : '↺ Recompute'}
        </button>
      </div>

      {/* Headline savings banner */}
      {s && (
        <div style={{
          background: 'linear-gradient(135deg, var(--green), var(--green-dark))',
          borderRadius: 'var(--radius-xl)',
          padding: '28px 32px',
          marginBottom: 24,
          color: '#fff',
          display: 'grid',
          gridTemplateColumns: '1fr 1fr 1fr 1fr',
          gap: 24,
          position: 'relative',
          overflow: 'hidden',
        }}>
          {/* Background decoration */}
          <div style={{
            position: 'absolute', right: -40, top: -40,
            width: 200, height: 200,
            background: 'rgba(255,255,255,0.05)',
            borderRadius: '50%',
          }} />
          {[
            { label: 'Water Saved',  value: `${s.water_saved_mm.toFixed(0)}`, unit: 'mm', sub: `vs ${s.blind_water_mm.toFixed(0)}mm blind` },
            { label: 'Cost Saved',   value: `₹${s.cost_saved_inr.toFixed(0)}`, unit: '', sub: `vs ₹${s.blind_cost_inr.toFixed(0)} blind` },
            { label: 'Events Saved', value: `${Math.max(0, s.blind_baseline_events - s.actual_events)}`, unit: 'events', sub: `${s.actual_events} vs ${s.blind_baseline_events}` },
            { label: 'Savings %',    value: `${s.savings_pct_water.toFixed(0)}`, unit: '%', sub: 'water reduction' },
          ].map(item => (
            <div key={item.label}>
              <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.6)', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>
                {item.label}
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 30, fontWeight: 800, letterSpacing: '-0.03em', lineHeight: 1 }}>
                {item.value}
                <span style={{ fontSize: 16, fontWeight: 400, marginLeft: 4, opacity: 0.75 }}>{item.unit}</span>
              </div>
              <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.55)', marginTop: 4 }}>{item.sub}</div>
            </div>
          ))}
        </div>
      )}

      {/* Metric cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        <MetricCard label="Actual Events"   value={s?.actual_events ?? '—'}          unit="irr"   sublabel="Confirmed by you"       loading={isLoading} />
        <MetricCard label="Blind Baseline"  value={s?.blind_baseline_events ?? '—'}  unit="irr"   sublabel="Every 10 days"           loading={isLoading} />
        <MetricCard label="Actual Water"    value={s?.actual_water_mm?.toFixed(0) ?? '—'} unit="mm" sublabel="ELISA-managed"      loading={isLoading} variant="green" />
        <MetricCard label="Stress Days"     value={s?.stress_days ?? '—'}            unit="days"  sublabel="SM below PWP"           loading={isLoading} variant={s?.stress_days > 5 ? 'alert' : 'default'} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 20 }}>

        {/* Comparison bar chart */}
        <div className="card">
          <div className="card-title">ELISA vs Blind — {s?.season}</div>
          {isLoading ? (
            <div className="skeleton" style={{ height: 220, marginTop: 12 }} />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={comparisonData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--mist)" vertical={false} />
                <XAxis dataKey="name" tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} width={40} />
                <Tooltip content={<CustomTooltip />} />
                <Legend formatter={v => <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}>{v}</span>} />
                <Bar dataKey="ELISA" fill="var(--green)" radius={[4,4,0,0]} maxBarSize={40} />
                <Bar dataKey="Blind" fill="var(--clay)"  radius={[4,4,0,0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Savings history */}
        <div className="card">
          <div className="card-title">Savings History</div>
          {histChartData.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 14, textAlign: 'center', padding: '32px 0' }}>
              No historical data yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={histChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--mist)" vertical={false} />
                <XAxis dataKey="season" tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="water" tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }} axisLine={false} tickLine={false} width={36} />
                <YAxis yAxisId="cost" orientation="right" tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: 'var(--wheat)' }} axisLine={false} tickLine={false} width={40} />
                <Tooltip content={<CustomTooltip />} />
                <Bar yAxisId="water" dataKey="water_saved" name="Water saved (mm)" fill="var(--green)" radius={[4,4,0,0]} maxBarSize={32} />
                <Bar yAxisId="cost"  dataKey="cost_saved"  name="Cost saved (₹)"  fill="var(--wheat)"  radius={[4,4,0,0]} maxBarSize={32} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Methodology note */}
      <div className="card" style={{ background: 'var(--paper)', border: '1px solid var(--mist)' }}>
        <div className="card-title">Methodology</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 32px', fontSize: 13, color: 'var(--text-muted)' }}>
          {[
            ['Baseline', 'Blind farmer: irrigate every 10 days, 80mm, regardless of SM or rain.'],
            ['ELISA',    'Irrigate only when MPC C1 forecast says SM will drop below trigger.'],
            ['Energy',   '5HP pump (3.73kW), η=0.65, 2h run = 11.47 kWh/event.'],
            ['Tariff',   'Weighted average of Low (₹3.50) + Medium (₹6.00) UPPCL IEX rates.'],
            ['Water',    'Actual: sum of confirmed irrigation events. Blind: simulated FAO-56.'],
            ['Dataset',  'ERA5-Land SM 2015–2024. PatchTST trained on 2015–2022, tested 2024.'],
          ].map(([k, v]) => (
            <div key={k} style={{ paddingBottom: 8, borderBottom: '1px solid var(--mist)' }}>
              <div style={{ fontWeight: 600, color: 'var(--text-main)', marginBottom: 2 }}>{k}</div>
              {v}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}