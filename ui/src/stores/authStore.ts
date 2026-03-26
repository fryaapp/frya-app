import { create } from 'zustand'
import { api } from '../lib/api'

/** 5 minutes in milliseconds — proactive refresh fires this long before expiry */
const REFRESH_MARGIN_MS = 5 * 60 * 1000

interface LoginResponse {
  access_token: string
  refresh_token: string
  expires_in: number
}

interface AuthState {
  token: string | null
  refreshToken: string | null
  expiresAt: number | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  restore: () => void
  refresh: () => Promise<void>
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null

function clearRefreshTimer() {
  if (refreshTimer !== null) {
    clearTimeout(refreshTimer)
    refreshTimer = null
  }
}

export const useAuthStore = create<AuthState>((set, get) => {
  /** Schedule a proactive token refresh 5 min before expiry */
  function scheduleRefresh(expiresAt: number) {
    clearRefreshTimer()
    const delay = expiresAt - Date.now() - REFRESH_MARGIN_MS
    if (delay <= 0) {
      // Already within the margin — refresh immediately
      get().refresh()
      return
    }
    refreshTimer = setTimeout(() => {
      get().refresh()
    }, delay)
  }

  /** Apply new tokens to memory, localStorage, and api client */
  function applyTokens(accessToken: string, refreshTk: string, expiresIn: number) {
    const expiresAt = Date.now() + expiresIn * 1000

    api.setToken(accessToken)
    api.setRefreshToken(refreshTk)

    // access_token only in memory (api client); refresh_token in localStorage
    localStorage.setItem('frya-refresh', refreshTk)
    localStorage.setItem('frya-expires-at', String(expiresAt))
    // Keep frya-token in localStorage for restore across page reloads
    localStorage.setItem('frya-token', accessToken)

    set({ token: accessToken, refreshToken: refreshTk, expiresAt, isAuthenticated: true })
    scheduleRefresh(expiresAt)
  }

  // Register the logout callback with api client (handles refresh failures)
  api.onUnauthorized(() => {
    get().logout()
  })

  return {
    token: null,
    refreshToken: null,
    expiresAt: null,
    isAuthenticated: false,

    login: async (email, password) => {
      const data = await api.post<LoginResponse>('/auth/login', { email, password })
      applyTokens(data.access_token, data.refresh_token, data.expires_in)
    },

    logout: () => {
      clearRefreshTimer()
      api.setToken(null)
      api.setRefreshToken(null)
      localStorage.removeItem('frya-token')
      localStorage.removeItem('frya-refresh')
      localStorage.removeItem('frya-expires-at')
      set({ token: null, refreshToken: null, expiresAt: null, isAuthenticated: false })
    },

    restore: () => {
      const token = localStorage.getItem('frya-token')
      const refresh = localStorage.getItem('frya-refresh')
      const expiresAtStr = localStorage.getItem('frya-expires-at')
      const expiresAt = expiresAtStr ? Number(expiresAtStr) : null

      if (token && refresh) {
        api.setToken(token)
        api.setRefreshToken(refresh)
        set({ token, refreshToken: refresh, expiresAt, isAuthenticated: true })

        if (expiresAt) {
          scheduleRefresh(expiresAt)
        }
      }
    },

    refresh: async () => {
      const { refreshToken } = get()
      if (!refreshToken) {
        get().logout()
        return
      }

      try {
        // Use api.tryRefresh() which deduplicates concurrent refresh calls
        const newAccessToken = await api.tryRefresh()

        // tryRefresh updates the api client internally; sync store state
        const expiresAt = Date.now() + 3600 * 1000 // default 1h if not returned
        localStorage.setItem('frya-token', newAccessToken)
        localStorage.setItem('frya-expires-at', String(expiresAt))
        set({ token: newAccessToken, expiresAt })

        scheduleRefresh(expiresAt)
      } catch {
        // tryRefresh already calls onUnauthorized which triggers logout
      }
    },
  }
})
