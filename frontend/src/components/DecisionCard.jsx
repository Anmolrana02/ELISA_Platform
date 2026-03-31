// Paste contents from the generated DecisionCard.jsx here
// src/components/DecisionCard.jsx
/**
 * DecisionCard — renders the MPC irrigation decision prominently.
 *
 * Props:
 *   prediction  object   — from /predict API
 *   loading     bool
 *   onConfirm   fn       — called when farmer taps "I irrigated"
 *   confirming  bool     — loading state for confirm action
 */
export default function DecisionCard({ prediction, loading, onConfirm, confirming }) {
  if (loading) {
    return (
      <div className="card" style={{ padding: 32 }}>
        <div className="skeleton" style={{ height: 24, width: '50%', marginBottom: 16 }} />
        <div className="skeleton" style={{ height: 48, width: '80%', marginBottom: 12 }} />
        <div className="skeleton" style={{ height: 16, width: '90%', marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 16, width: '70%' }} />
      </div>
    )
  }

  if (!prediction) {
    return (
      <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>🌱</div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600 }}>
          No prediction yet
        </div>
        <div style={{ fontSize: 14, marginTop: 4 }}>
          Prediction runs at 05:00 IST each morning.
        </div>
      </div>
    )
  }

  const irrigate = prediction.irrigate

  return (
    <div
      className="card"
      style={{
        padding: 0,
        overflow: 'hidden',
        border: `2px solid ${irrigate ? 'rgba(196,92,58,0.3)' : 'rgba(29,158,117,0.25)'}`,
        boxShadow: irrigate
          ? '0 4px 24px rgba(196,92,58,0.12)'
          : '0 4px 24px rgba(29,158,117,0.08)',
      }}
    >
      {/* Header bar */}
      <div style={{
        background: irrigate ? 'var(--alert)' : 'var(--green)',
        padding: '20px 28px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
      }}>
        <div style={{ fontSize: 36, lineHeight: 1 }}>
          {irrigate ? '💧' : '✅'}
        </div>
        <div>
          <div style={{
            fontFamily: 'var(--font-display)',
            fontSize: 22,
            fontWeight: 800,
            color: '#fff',
            letterSpacing: '-0.03em',
          }}>
            {irrigate ? 'Irrigate Today' : 'No Irrigation Needed'}
          </div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.8)', marginTop: 2 }}>
            {prediction.from_cache ? `Prediction for ${prediction.date}` : 'Just computed'}
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '24px 28px' }}>
        {/* Reason */}
        <p style={{
          fontSize: 15,
          color: 'var(--text-main)',
          lineHeight: 1.6,
          margin: '0 0 20px',
        }}>
          {prediction.reason || 'MPC analysis complete.'}
        </p>

        {/* Pump window (if irrigation needed) */}
        {irrigate && prediction.pump_start_hour !== null && (
          <div style={{
            background: '#FDF3D0',
            border: '1px solid rgba(212,165,63,0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '16px 20px',
            marginBottom: 20,
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 16,
          }}>
            <div>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                Pump Window
              </div>
              <div style={{ fontSize: 20, fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#7A5E0E' }}>
                {String(prediction.pump_start_hour).padStart(2, '0')}:00
                <span style={{ fontSize: 14, fontWeight: 400, margin: '0 4px' }}>→</span>
                {String(prediction.pump_end_hour).padStart(2, '0')}:00
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                Tariff
              </div>
              <div style={{ fontSize: 20, fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#7A5E0E', textTransform: 'capitalize' }}>
                {prediction.tariff_slot || '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
                Est. Cost
              </div>
              <div style={{ fontSize: 20, fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#7A5E0E' }}>
                ₹{prediction.cost_inr?.toFixed(2) || '—'}
              </div>
            </div>
          </div>
        )}

        {/* Rain suppression info */}
        {prediction.rain_24h_mm > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 13, color: 'var(--sky)',
            background: 'var(--sky-light)',
            padding: '10px 14px',
            borderRadius: 'var(--radius-sm)',
            marginBottom: 20,
          }}>
            🌧 Rain forecast: <strong>{prediction.rain_24h_mm?.toFixed(1)} mm</strong> in next 24h
          </div>
        )}

        {/* Confirm button */}
        {irrigate && (
          <button
            className="btn btn-primary btn-lg"
            onClick={onConfirm}
            disabled={confirming}
            style={{ width: '100%' }}
          >
            {confirming
              ? <><span className="spinner" /> Logging…</>
              : '✓ I Irrigated Today'}
          </button>
        )}

        {/* Method note */}
        <div style={{
          marginTop: 16,
          fontSize: 11,
          color: 'var(--text-faint)',
          fontFamily: 'var(--font-mono)',
          borderTop: '1px solid var(--mist)',
          paddingTop: 12,
        }}>
          Method: 48h MPC (C1 SM forecast → C2 rain check → C3 tariff optimisation)
          {prediction.energy_kwh && ` · ${prediction.energy_kwh.toFixed(3)} kWh`}
        </div>
      </div>
    </div>
  )
}