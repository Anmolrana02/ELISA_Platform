// Paste contents from the generated App.jsx here
// src/App.jsx
import { useState, createContext, useContext, useEffect } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate } from 'react-router-dom'
import { getToken, getUser, clearToken, clearUser } from './api/client'

import Login      from './pages/Login'
import FarmSetup  from './pages/FarmSetup'
import Dashboard  from './pages/Dashboard'
import Forecast   from './pages/Forecast'
import Decision   from './pages/Decision'
import Savings    from './pages/Savings'

// ── Farm context — selected farm shared across all pages ──────────────────────
export const FarmContext = createContext(null)
export const useFarm = () => useContext(FarmContext)

// ── Auth guard ────────────────────────────────────────────────────────────────
function RequireAuth({ children }) {
  const token = getToken()
  if (!token) return <Navigate to="/login" replace />
  return children
}

// ── Icons (inline SVG to avoid icon-library dep) ──────────────────────────────
const Icons = {
  dashboard: <svg viewBox="0 0 20 20" fill="currentColor"><path d="M2 10a8 8 0 1116 0A8 8 0 012 10zm5-1a1 1 0 011-1h4a1 1 0 110 2H8a1 1 0 01-1-1zm-1 4a1 1 0 000 2h8a1 1 0 000-2H6z"/></svg>,
  forecast:  <svg viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 3a1 1 0 000 2v8a2 2 0 002 2h2.586l-1.293 1.293a1 1 0 101.414 1.414L10 15.414l2.293 2.293a1 1 0 001.414-1.414L12.414 15H15a2 2 0 002-2V5a1 1 0 100-2H3zm11.707 4.707a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293a1 1 0 00-1.414 0l-2 2a1 1 0 101.414 1.414L8 10.414l1.293 1.293a1 1 0 001.414 0l4-4z" clipRule="evenodd"/></svg>,
  decision:  <svg viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd"/></svg>,
  savings:   <svg viewBox="0 0 20 20" fill="currentColor"><path d="M8.433 7.418c.155-.103.346-.196.567-.267v1.698a2.305 2.305 0 01-.567-.267C8.07 8.34 8 8.114 8 8c0-.114.07-.34.433-.582zM11 12.849v-1.698c.22.071.412.164.567.267.364.243.433.468.433.582 0 .114-.07.34-.433.582a2.305 2.305 0 01-.567.267z"/><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a4.535 4.535 0 00-1.676.662C6.602 6.234 6 7.009 6 8c0 .99.602 1.765 1.324 2.246.48.32 1.054.545 1.676.662v1.941c-.391-.127-.68-.317-.843-.504a1 1 0 10-1.51 1.31c.562.649 1.413 1.028 2.353 1.118V15a1 1 0 102 0v-.092a4.535 4.535 0 001.676-.662C13.398 13.766 14 12.991 14 12c0-.99-.602-1.765-1.324-2.246A4.535 4.535 0 0011 9.092V7.151c.391.127.68.317.843.504a1 1 0 101.511-1.31c-.563-.649-1.413-1.028-2.354-1.118V5z" clipRule="evenodd"/></svg>,
  farm:      <svg viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clipRule="evenodd"/></svg>,
  logout:    <svg viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M3 3a1 1 0 00-1 1v12a1 1 0 102 0V4a1 1 0 00-1-1zm10.293 9.293a1 1 0 001.414 1.414l3-3a1 1 0 000-1.414l-3-3a1 1 0 10-1.414 1.414L14.586 9H7a1 1 0 100 2h7.586l-1.293 1.293z" clipRule="evenodd"/></svg>,
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ farm, farms, onFarmChange }) {
  const navigate = useNavigate()
  const user = getUser()

  function handleLogout() {
    clearToken(); clearUser()
    navigate('/login')
  }

  const navItems = [
    { to: '/dashboard', label: 'Status',   icon: Icons.dashboard },
    { to: '/forecast',  label: 'Forecast', icon: Icons.forecast },
    { to: '/decision',  label: 'Decision', icon: Icons.decision },
    { to: '/savings',   label: 'Savings',  icon: Icons.savings },
  ]

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <h1>🌾 ELISA</h1>
        <p>Smart Irrigation v2.0</p>
      </div>

      {farm && (
        <div className="sidebar-farm">
          <div className="sidebar-farm-label">Active Farm</div>
          <div className="sidebar-farm-name">{farm.name}</div>
          <div className="sidebar-farm-district">{farm.district} · {farm.crop}</div>
        </div>
      )}

      {farms?.length > 1 && (
        <div style={{ padding: '4px 12px' }}>
          <select
            className="form-input form-select"
            style={{ fontSize: 13, padding: '8px 12px', background: 'rgba(255,255,255,0.08)', color: '#fff', borderColor: 'rgba(255,255,255,0.12)' }}
            value={farm?.id || ''}
            onChange={e => onFarmChange(e.target.value)}
          >
            {farms.map(f => (
              <option key={f.id} value={f.id} style={{ background: '#2D1F14' }}>{f.name}</option>
            ))}
          </select>
        </div>
      )}

      <nav className="sidebar-nav">
        {navItems.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <span className="icon">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
        <div className="divider" style={{ borderColor: 'rgba(255,255,255,0.08)', margin: '8px 0' }} />
        <NavLink to="/farms/new" className="nav-link">
          <span className="icon">{Icons.farm}</span>
          Add Farm
        </NavLink>
        <button
          onClick={handleLogout}
          className="nav-link"
          style={{ background: 'none', border: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}
        >
          <span className="icon">{Icons.logout}</span>
          Sign Out
        </button>
      </nav>

      <div className="sidebar-footer">
        {user?.name && <div style={{ color: 'rgba(255,255,255,0.5)', marginBottom: 4 }}>{user.name}</div>}
        Jamia Millia Islamia<br />
        EE Dept — Anmol & Nitin
      </div>
    </aside>
  )
}

// ── Mobile bottom nav ─────────────────────────────────────────────────────────
function MobileNav() {
  const items = [
    { to: '/dashboard', label: 'Status',   icon: Icons.dashboard },
    { to: '/forecast',  label: 'Forecast', icon: Icons.forecast },
    { to: '/decision',  label: 'Decision', icon: Icons.decision },
    { to: '/savings',   label: 'Savings',  icon: Icons.savings },
  ]
  return (
    <nav className="mobile-nav">
      {items.map(item => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
        >
          {item.icon}
          <span>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  )
}

// ── App shell (authenticated layout) ─────────────────────────────────────────
function AppShell({ children }) {
  const { farm, farms, setActiveFarmId } = useFarm()

  return (
    <div className="app-shell">
      <Sidebar farm={farm} farms={farms} onFarmChange={setActiveFarmId} />
      <main className="main-content page-enter">
        {children}
      </main>
      <MobileNav />
    </div>
  )
}

// ── Root with farm context provider ──────────────────────────────────────────
function FarmProvider({ children }) {
  const [farms, setFarms] = useState([])
  const [activeFarmId, setActiveFarmId] = useState(null)

  const farm = farms.find(f => f.id === activeFarmId) || farms[0] || null

  // Persist selected farm across refreshes
  useEffect(() => {
    const saved = localStorage.getItem('elisa_farm_id')
    if (saved) setActiveFarmId(saved)
  }, [])

  useEffect(() => {
    if (activeFarmId) localStorage.setItem('elisa_farm_id', activeFarmId)
  }, [activeFarmId])

  return (
    <FarmContext.Provider value={{ farm, farms, setFarms, activeFarmId, setActiveFarmId }}>
      {children}
    </FarmContext.Provider>
  )
}

// ── Router ────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <BrowserRouter>
      <FarmProvider>
        <Routes>
          <Route path="/login"     element={<Login />} />
          <Route path="/farms/new" element={<RequireAuth><FarmSetup /></RequireAuth>} />
          <Route path="/dashboard" element={<RequireAuth><AppShell><Dashboard /></AppShell></RequireAuth>} />
          <Route path="/forecast"  element={<RequireAuth><AppShell><Forecast /></AppShell></RequireAuth>} />
          <Route path="/decision"  element={<RequireAuth><AppShell><Decision /></AppShell></RequireAuth>} />
          <Route path="/savings"   element={<RequireAuth><AppShell><Savings /></AppShell></RequireAuth>} />
          <Route path="*"          element={<Navigate to={getToken() ? '/dashboard' : '/login'} replace />} />
        </Routes>
      </FarmProvider>
    </BrowserRouter>
  )
}