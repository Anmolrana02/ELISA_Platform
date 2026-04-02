// Paste contents from the generated Login.jsx here
// src/pages/Login.jsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi, setToken, setUser } from '../api/client'

export default function Login() {
  const navigate = useNavigate()

  const [step,     setStep]    = useState('phone')   // 'phone' | 'otp' | 'name'
  const [phone,    setPhone]   = useState('')
  const [otp,      setOtp]     = useState('')
  const [name,     setName]    = useState('')
  const [language, setLang]    = useState('hi')
  const [isNew,    setIsNew]   = useState(false)
  const [loading,  setLoading] = useState(false)
  const [error,    setError]   = useState('')
  const [info,     setInfo]    = useState('')

  async function handleSendOtp(e) {
    e.preventDefault()
    if (!phone.trim()) return
    setLoading(true); setError('')
    try {
      const res = await authApi.sendOtp(phone)
      if (res.data.dev_otp) {
        setInfo(`[DEV MODE] OTP: ${res.data.dev_otp}`)
      } else {
        setInfo(`OTP sent to ${res.data.phone}. Valid for ${res.data.expires_in_seconds / 60} min.`)
      }
      setStep('otp')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to send OTP.')
    } finally {
      setLoading(false)
    }
  }

  async function handleVerifyOtp(e) {
    e.preventDefault()
    setLoading(true); setError('')
    
    // If we are on the name step, include the name
    const nameToSend = step === 'name' ? name : undefined
    
    try {
      const res = await authApi.verifyOtp(phone, otp, nameToSend || undefined, language)
      setToken(res.data.access_token)
      setUser(res.data.user)
      // New user goes to farm setup, returning user goes to dashboard
      navigate(res.data.user ? '/dashboard' : '/farms/new', { replace: true })
    } catch (err) {
      const detail = err.response?.data?.detail || ''
      if (detail.includes('Name is required')) {
        // OTP is still valid — just need the name
        setIsNew(true)
        setStep('name')
        setError('')
      } else {
        setError(detail || 'Verification failed. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

async function handleRegister(e) {
    e.preventDefault()
    if (!name.trim()) { setError('Please enter your name.'); return }
    // Call the same verify function — it now has the name
    return handleVerifyOtp(e)
  }

  return (
    <div style={{
      minHeight: '100dvh',
      background: 'var(--soil)',
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      overflow: 'hidden',
    }}>
      {/* ── Left: Branding ─────────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', flexDirection: 'column',
        justifyContent: 'center', padding: '60px 64px',
        position: 'relative', overflow: 'hidden',
      }}>
        {/* Background texture */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: `
            radial-gradient(ellipse at 20% 50%, rgba(212,165,63,0.08) 0%, transparent 60%),
            radial-gradient(ellipse at 80% 20%, rgba(29,158,117,0.06) 0%, transparent 50%)
          `,
        }} />

        <div style={{ position: 'relative' }}>
          <div style={{ fontSize: 48, marginBottom: 20 }}>🌾</div>
          <h1 style={{
            fontFamily: 'var(--font-display)',
            fontSize: 52, fontWeight: 800,
            color: '#fff',
            letterSpacing: '-0.04em',
            lineHeight: 1,
            marginBottom: 8,
          }}>
            ELISA<br />
            <span style={{ color: 'var(--wheat)', fontSize: 38 }}>Platform</span>
          </h1>
          <p style={{
            fontSize: 16, color: 'rgba(255,255,255,0.55)',
            maxWidth: 340, lineHeight: 1.7, margin: '20px 0 40px',
          }}>
            Smart irrigation decisions for Western UP farmers.
            Powered by PatchTST forecasting and 48h MPC optimization.
          </p>

          {/* Feature list */}
          {[
            ['💧', '7-day soil moisture forecast'],
            ['⚡', 'Cheapest tariff pump window'],
            ['🌧', 'Rain-suppression (OpenMeteo)'],
            ['📱', 'WhatsApp irrigation alerts'],
          ].map(([icon, text]) => (
            <div key={text} style={{
              display: 'flex', alignItems: 'center', gap: 12,
              marginBottom: 12,
            }}>
              <span style={{ fontSize: 18 }}>{icon}</span>
              <span style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)' }}>{text}</span>
            </div>
          ))}

          <div style={{
            marginTop: 48,
            paddingTop: 24,
            borderTop: '1px solid rgba(255,255,255,0.1)',
            fontSize: 12,
            color: 'rgba(255,255,255,0.3)',
            fontFamily: 'var(--font-mono)',
          }}>
            Jamia Millia Islamia · EE Dept<br />
            Anmol Rana &amp; Nitin Gaurav · Dr. Zainul Abidin Jaffery
          </div>
        </div>
      </div>

      {/* ── Right: Auth form ───────────────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '40px',
        background: 'var(--paper)',
        borderRadius: '32px 0 0 32px',
      }}>
        <div style={{ width: '100%', maxWidth: 380 }}>

          {/* Step indicator */}
          <div style={{
            display: 'flex', gap: 6, marginBottom: 32,
          }}>
            {['phone', 'otp', 'name'].map((s, i) => (
              <div key={s} style={{
                height: 3, flex: 1,
                borderRadius: 99,
                background: step === s || (step === 'name' && i <= 2) || (step === 'otp' && i <= 1) || (step === 'phone' && i === 0)
                  ? 'var(--green)' : 'var(--mist)',
                transition: 'background 0.3s',
              }} />
            ))}
          </div>

          {step === 'phone' && (
            <>
              <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700, marginBottom: 6 }}>
                Sign in
              </h2>
              <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 28 }}>
                Enter your mobile number to receive an OTP via SMS.
              </p>
              <form onSubmit={handleSendOtp}>
                <div className="form-group">
                  <label className="form-label">Mobile Number</label>
                  <input
                    className="form-input"
                    type="tel"
                    placeholder="+91 XXXXX XXXXX"
                    value={phone}
                    onChange={e => setPhone(e.target.value)}
                    autoFocus
                    required
                    style={{ fontSize: 18, fontFamily: 'var(--font-mono)', letterSpacing: '0.05em' }}
                  />
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                    Format: 9876543210 or +919876543210
                  </div>
                </div>
                {error && <div className="alert-banner alert-banner-alert" style={{ marginBottom: 16 }}>{error}</div>}
                <button type="submit" className="btn btn-primary btn-lg" style={{ width: '100%' }} disabled={loading}>
                  {loading ? <><span className="spinner" /> Sending…</> : 'Send OTP →'}
                </button>
              </form>
            </>
          )}

          {step === 'otp' && (
            <>
              <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700, marginBottom: 6 }}>
                Enter OTP
              </h2>
              <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 28 }}>
                We sent a 6-digit code to <strong style={{ color: 'var(--text-main)' }}>{phone}</strong>.
              </p>
              {info && (
                <div className="alert-banner alert-banner-wheat" style={{ marginBottom: 16 }}>
                  {info}
                </div>
              )}
              <form onSubmit={handleVerifyOtp}>
                <div className="form-group">
                  <label className="form-label">One-Time Password</label>
                  <input
                    className="form-input otp-input"
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    placeholder="——————"
                    value={otp}
                    onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
                    autoFocus
                    required
                  />
                </div>
                {error && <div className="alert-banner alert-banner-alert" style={{ marginBottom: 16 }}>{error}</div>}
                <button type="submit" className="btn btn-primary btn-lg" style={{ width: '100%' }} disabled={loading || otp.length < 6}>
                  {loading ? <><span className="spinner" /> Verifying…</> : 'Verify OTP →'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost"
                  style={{ width: '100%', marginTop: 10 }}
                  onClick={() => { setStep('phone'); setOtp(''); setError(''); setInfo('') }}
                >
                  ← Change number
                </button>
              </form>
            </>
          )}

          {step === 'name' && (
            <>
              <h2 style={{ fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700, marginBottom: 6 }}>
                Welcome!
              </h2>
              <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 28 }}>
                First time here. Tell us your name and preferred language.
              </p>
              <form onSubmit={handleRegister}>
                <div className="form-group">
                  <label className="form-label">Your Name</label>
                  <input
                    className="form-input"
                    type="text"
                    placeholder="e.g. Ramesh Kumar"
                    value={name}
                    onChange={e => setName(e.target.value)}
                    autoFocus required
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">WhatsApp Language</label>
                  <select
                    className="form-input form-select"
                    value={language}
                    onChange={e => setLang(e.target.value)}
                  >
                    <option value="hi">हिंदी (Hindi)</option>
                    <option value="en">English</option>
                  </select>
                </div>
                {error && <div className="alert-banner alert-banner-alert" style={{ marginBottom: 16 }}>{error}</div>}
                <button type="submit" className="btn btn-primary btn-lg" style={{ width: '100%' }} disabled={loading || !name.trim()}>
                  {loading ? <><span className="spinner" /> Creating account…</> : 'Create Account →'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          div[style*="grid-template-columns: 1fr 1fr"] {
            grid-template-columns: 1fr !important;
          }
          div[style*="borderRadius: '32px 0 0 32px'"] {
            border-radius: 0 !important;
          }
        }
      `}</style>
    </div>
  )
}