// Paste contents from the generated SMChart.jsx here
// src/components/SMChart.jsx
/**
 * SMChart — 7-day soil moisture forecast chart with rain bars.
 *
 * Props:
 *   smForecast   float[]   — 7 SM values in mm
 *   rainDaily    float[]   — 7 daily rain totals in mm
 *   currentSM    float     — today's SM (plotted as day 0)
 *   triggerMM    float     — crop trigger line
 *   fcMM         float     — field capacity line
 *   pwpMM        float     — PWP line
 *   loading      bool
 *   height       number    — chart height px
 */
import {
  ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{
      background: '#fff',
      border: '1px solid var(--mist)',
      borderRadius: 'var(--radius-md)',
      padding: '12px 16px',
      boxShadow: 'var(--shadow-md)',
      fontFamily: 'var(--font-mono)',
      fontSize: 13,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 8, color: 'var(--text-muted)' }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color, marginBottom: 3 }}>
          {p.name}: <strong>{p.value?.toFixed(1)}</strong>
          {p.name === 'SM' ? ' mm' : ' mm'}
        </div>
      ))}
    </div>
  )
}

export default function SMChart({
  smForecast = [],
  rainDaily  = [],
  currentSM,
  triggerMM,
  fcMM,
  pwpMM,
  loading = false,
  height = 280,
}) {
  if (loading) {
    return (
      <div
        className="skeleton"
        style={{ height, borderRadius: 'var(--radius-lg)', width: '100%' }}
      />
    )
  }

  // Build data points: Day 0 = today (actual), Days 1–7 = forecast
  const today = new Date()
  const fmt = (d) => d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric' })

  const data = [
    // Day 0 — current observed
    ...(currentSM !== undefined ? [{
      day:  `${fmt(today)} ★`,
      SM:   Math.round(currentSM * 10) / 10,
      Rain: rainDaily[0] || 0,
      isToday: true,
    }] : []),
    // Days 1–7 — forecast
    ...smForecast.map((sm, i) => {
      const d = new Date(today)
      d.setDate(d.getDate() + i + 1)
      return {
        day:  fmt(d),
        SM:   Math.round(sm * 10) / 10,
        Rain: rainDaily[i + 1] || 0,
        isToday: false,
      }
    }),
  ]

  // Colour each SM point by status relative to trigger
  const smColor = (sm) => {
    if (!triggerMM) return 'var(--green)'
    if (sm < pwpMM)     return 'var(--alert)'
    if (sm < triggerMM) return '#EF9F27'
    return 'var(--green)'
  }

  // Custom dot to colour individual points
  const CustomDot = (props) => {
    const { cx, cy, payload } = props
    const color = smColor(payload.SM)
    return <circle cx={cx} cy={cy} r={5} fill={color} stroke="#fff" strokeWidth={2} />
  }

  const yMin = Math.max(0, Math.min(...data.map(d => d.SM)) - 20)
  const yMax = fcMM ? fcMM + 20 : Math.max(...data.map(d => d.SM)) + 30

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--mist)"
          vertical={false}
        />
        <XAxis
          dataKey="day"
          tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          yAxisId="sm"
          domain={[yMin, yMax]}
          tick={{ fontSize: 11, fontFamily: 'var(--font-mono)', fill: 'var(--text-muted)' }}
          axisLine={false}
          tickLine={false}
          tickFormatter={v => `${v}`}
          width={38}
        />
        <YAxis
          yAxisId="rain"
          orientation="right"
          domain={[0, Math.max(10, ...data.map(d => d.Rain)) * 1.5]}
          tick={{ fontSize: 10, fontFamily: 'var(--font-mono)', fill: '#4A9CC4' }}
          axisLine={false}
          tickLine={false}
          width={32}
          tickFormatter={v => `${v}`}
        />
        <Tooltip content={<CustomTooltip />} />
        <Legend
          formatter={(value) => (
            <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
              {value === 'SM' ? 'Soil Moisture (mm)' : 'Rain forecast (mm)'}
            </span>
          )}
        />

        {/* Reference lines */}
        {triggerMM && (
          <ReferenceLine
            yAxisId="sm"
            y={triggerMM}
            stroke="var(--alert)"
            strokeDasharray="6 3"
            strokeWidth={1.5}
            label={{
              value: `Trigger ${triggerMM.toFixed(0)}mm`,
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              fill: 'var(--alert)',
              position: 'insideTopLeft',
            }}
          />
        )}
        {fcMM && (
          <ReferenceLine
            yAxisId="sm"
            y={fcMM}
            stroke="var(--green)"
            strokeDasharray="4 4"
            strokeWidth={1}
            label={{
              value: `FC ${fcMM.toFixed(0)}mm`,
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              fill: 'var(--green)',
              position: 'insideTopRight',
            }}
          />
        )}
        {pwpMM && (
          <ReferenceLine
            yAxisId="sm"
            y={pwpMM}
            stroke="#aaa"
            strokeDasharray="2 4"
            strokeWidth={1}
          />
        )}

        {/* Rain bars */}
        <Bar
          yAxisId="rain"
          dataKey="Rain"
          fill="var(--sky)"
          opacity={0.55}
          radius={[3, 3, 0, 0]}
          maxBarSize={24}
          name="Rain"
        />

        {/* SM line */}
        <Line
          yAxisId="sm"
          type="monotone"
          dataKey="SM"
          stroke="var(--green)"
          strokeWidth={2.5}
          dot={<CustomDot />}
          activeDot={{ r: 7, strokeWidth: 2 }}
          name="SM"
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}