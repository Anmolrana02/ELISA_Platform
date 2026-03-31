// Paste contents from the generated api/client.js here
// src/api/client.js
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || ''

export const api = axios.create({
  baseURL: `${BASE}/api/v1`,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Token helpers ─────────────────────────────────────────────────────────────
export const getToken  = ()          => localStorage.getItem('elisa_token')
export const setToken  = (t)         => localStorage.setItem('elisa_token', t)
export const clearToken= ()          => localStorage.removeItem('elisa_token')
export const getUser   = ()          => {
  try { return JSON.parse(localStorage.getItem('elisa_user') || 'null') }
  catch { return null }
}
export const setUser   = (u)         => localStorage.setItem('elisa_user', JSON.stringify(u))
export const clearUser = ()          => localStorage.removeItem('elisa_user')

export function logout() {
  clearToken(); clearUser()
  window.location.href = '/login'
}

// ── Request interceptor — attach JWT ─────────────────────────────────────────
api.interceptors.request.use(cfg => {
  const t = getToken()
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})

// ── Response interceptor — handle 401 ────────────────────────────────────────
api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      clearToken(); clearUser()
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────────
export const authApi = {
  sendOtp:   (phone)              => api.post('/auth/send-otp',   { phone }),
  verifyOtp: (phone, otp, name, language) =>
    api.post('/auth/verify-otp', { phone, otp, name, language }),
  me:        ()                   => api.get('/auth/me/full'),
  updatePrefs: (prefs)            => api.patch('/auth/me/preferences', null, { params: prefs }),
}

// ── Farms ─────────────────────────────────────────────────────────────────────
export const farmsApi = {
  list:   ()           => api.get('/farms'),
  get:    (id)         => api.get(`/farms/${id}`),
  create: (body)       => api.post('/farms', body),
  update: (id, params) => api.patch(`/farms/${id}`, null, { params }),
  delete: (id)         => api.delete(`/farms/${id}`),
}

// ── Predictions ───────────────────────────────────────────────────────────────
export const predictApi = {
  get:     (farmId, force = false) => api.get(`/farms/${farmId}/predict`, { params: { force } }),
  history: (farmId, days = 14)     => api.get(`/farms/${farmId}/predict/history`, { params: { days } }),
}

// ── Weather ───────────────────────────────────────────────────────────────────
export const weatherApi = {
  get:    (farmId) => api.get(`/farms/${farmId}/weather`),
  hourly: (farmId) => api.get(`/farms/${farmId}/weather/hourly`),
}

// ── Irrigation ────────────────────────────────────────────────────────────────
export const irrigationApi = {
  confirm: (farmId, date, mm) => api.post(`/farms/${farmId}/confirm-irrigation`, { date, mm }),
  history: (farmId, days = 60) => api.get(`/farms/${farmId}/confirm-irrigation/history`, { params: { days } }),
}

// ── Savings ───────────────────────────────────────────────────────────────────
export const savingsApi = {
  get:        (farmId, season) => api.get(`/farms/${farmId}/savings`, season ? { params: { season } } : {}),
  history:    (farmId)         => api.get(`/farms/${farmId}/savings/history`),
  recompute:  (farmId)         => api.put(`/farms/${farmId}/savings/recompute`),
}

// ── Agronomy constants (from /health response ML section) ─────────────────────
export const healthApi = {
  get: () => axios.get(`${BASE}/health`),
}