// Paste contents from the generated MetricCard.jsx here
// src/components/MetricCard.jsx
/**
 * MetricCard — displays a single numeric metric with label, unit, and trend.
 *
 * Props:
 *   label       string   — card title (e.g. "Soil Moisture")
 *   value       number|string — main value to display
 *   unit        string   — unit suffix (e.g. "mm", "₹", "%")
 *   sublabel    string   — secondary line (e.g. "Trigger: 135 mm")
 *   trend       'up'|'down'|null
 *   variant     'default'|'green'|'wheat'|'alert'|'sky'
 *   loading     bool
 *   size        'sm'|'md'|'lg'
 */
export default function MetricCard({
  label,
  value,
  unit = '',
  sublabel,
  trend,
  variant = 'default',
  loading = false,
  size = 'md',
  icon,
  onClick,
}) {
  const variantStyles = {
    default: { bg: '#fff',                border: 'var(--mist)',         accent: 'var(--text-main)' },
    green:   { bg: 'var(--green-light)',   border: 'rgba(29,158,117,.2)', accent: 'var(--green-dark)' },
    wheat:   { bg: '#FDF3D0',             border: 'rgba(212,165,63,.25)',accent: '#7A5E0E' },
    alert:   { bg: 'var(--alert-light)',   border: 'rgba(196,92,58,.2)',  accent: 'var(--alert)' },
    sky:     { bg: 'var(--sky-light)',     border: 'rgba(74,156,196,.2)', accent: '#2A6E94' },
  }

  const sizes = {
    sm: { valueSize: 20, padding: '14px 16px', labelSize: 11 },
    md: { valueSize: 28, padding: '20px 22px', labelSize: 12 },
    lg: { valueSize: 36, padding: '26px 28px', labelSize: 13 },
  }

  const s = variantStyles[variant] || variantStyles.default
  const z = sizes[size] || sizes.md

  const TrendArrow = () => {
    if (!trend) return null
    return (
      <span style={{
        fontSize: 12,
        fontFamily: 'var(--font-mono)',
        color: trend === 'up' ? 'var(--green)' : 'var(--alert)',
        marginLeft: 4,
      }}>
        {trend === 'up' ? '↑' : '↓'}
      </span>
    )
  }

  if (loading) {
    return (
      <div style={{
        background: '#fff',
        border: `1px solid var(--mist)`,
        borderRadius: 'var(--radius-lg)',
        padding: z.padding,
        boxShadow: 'var(--shadow-sm)',
      }}>
        <div className="skeleton" style={{ height: 12, width: '60%', marginBottom: 12 }} />
        <div className="skeleton" style={{ height: z.valueSize, width: '40%', marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 11, width: '70%' }} />
      </div>
    )
  }

  return (
    <div
      onClick={onClick}
      style={{
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderRadius: 'var(--radius-lg)',
        padding: z.padding,
        boxShadow: 'var(--shadow-sm)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'transform 0.15s ease, box-shadow 0.15s ease',
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={e => {
        if (onClick) {
          e.currentTarget.style.transform = 'translateY(-2px)'
          e.currentTarget.style.boxShadow = 'var(--shadow-md)'
        }
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = 'var(--shadow-sm)'
      }}
    >
      {/* Decorative accent bar */}
      <div style={{
        position: 'absolute',
        top: 0, left: 0, right: 0,
        height: 3,
        background: s.accent,
        opacity: 0.5,
        borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
      }} />

      <div style={{
        fontSize: z.labelSize,
        fontWeight: 600,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.07em',
        fontFamily: 'var(--font-mono)',
        marginBottom: 8,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}>
        {icon && <span>{icon}</span>}
        {label}
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 2 }}>
        <span style={{
          fontSize: z.valueSize,
          fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          color: s.accent,
          letterSpacing: '-0.03em',
          lineHeight: 1,
        }}>
          {value ?? '—'}
        </span>
        {unit && (
          <span style={{
            fontSize: z.valueSize * 0.46,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            marginLeft: 3,
          }}>
            {unit}
          </span>
        )}
        <TrendArrow />
      </div>

      {sublabel && (
        <div style={{
          fontSize: 12,
          color: 'var(--text-muted)',
          marginTop: 6,
          fontFamily: 'var(--font-body)',
        }}>
          {sublabel}
        </div>
      )}
    </div>
  )
}