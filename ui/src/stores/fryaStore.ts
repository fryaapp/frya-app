import { create } from 'zustand'
import { api } from '../lib/api'
// API_BASE from constants is available if needed for REST fallback

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MessageRole = 'user' | 'frya' | 'system'

export interface ApprovalData {
  case_id: string
  case_number?: string
  vendor: string
  amount: number
  currency?: string
  document_type?: string
  buttons: string[]
}

export interface DuplicateData {
  original_title: string
  paperless_id: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  content_blocks?: any[]
  actions?: any[]
  timestamp: number
  suggestions?: string[]
  caseRef?: string | null
  contextType?: string
  isStreaming?: boolean
  approval?: ApprovalData
  duplicate?: DuplicateData
  notificationType?: string
  approvalAction?: string
}

interface LoginResponse {
  access_token: string
  refresh_token: string
  expires_in: number
}

type WsMessageIncoming =
  | { type: 'pong' }
  | { type: 'typing'; active: boolean; hint?: string }
  | { type: 'chunk'; text: string }
  | { type: 'message_complete'; text: string; case_ref: string | null; suggestions: string[]; context_type?: string; content_blocks?: any[]; actions?: any[]; routing?: string }
  | { type: 'approval_request'; case_id: string; case_number?: string; vendor: string; amount: number; currency?: string; buttons: string[]; document_type?: string }
  | { type: 'notification'; text: string; notification_type: string }
  | { type: 'duplicate'; original_title: string; paperless_id: number }
  | { type: 'ui_hint'; action: string; context_type?: string }
  | { type: 'error'; message: string }
  | { type: string; text?: string; reply?: string; message?: string; content_blocks?: any[]; actions?: any[]; [key: string]: any }

// ---------------------------------------------------------------------------
// Store interface
// ---------------------------------------------------------------------------

interface PdfViewerState {
  caseId: string
  title: string
}

interface FryaStore {
  // Auth
  token: string | null
  refreshToken: string | null
  expiresAt: number | null
  isAuthenticated: boolean
  isRestored: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  restore: () => void

  // UI
  showGreeting: boolean
  showSettings: boolean
  pdfViewer: PdfViewerState | null
  startChat: (initialMessage?: string) => void
  goHome: () => void
  openSettings: () => void
  openPdfViewer: (caseId: string, title: string) => void
  closePdfViewer: () => void

  // Chat
  messages: ChatMessage[]
  isTyping: boolean
  typingHint: string | null
  streamingId: string | null
  addUserMessage: (text: string) => void
  addFryaMessage: (msg: { text: string; content_blocks?: any[]; actions?: any[] }) => void
  setTyping: (active: boolean, hint?: string) => void
  addApprovalRequest: (data: ApprovalData) => void
  addNotification: (text: string, notificationType: string) => void
  addDuplicate: (data: DuplicateData) => void
  setApprovalAction: (messageId: string, action: string) => void
  clearChat: () => void

  // WebSocket
  ws: WebSocket | null
  wsConnected: boolean
  connect: () => void
  disconnect: () => void
  send: (msg: any) => void
  sendAction: (action: any) => void
  submitForm: (formId: string, formType: string, data: any) => void
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MARGIN_MS = 5 * 60 * 1000
const PING_INTERVAL_MS = 30_000
const WS_RECONNECT_DELAY_MS = 2_000
const WS_MAX_RETRIES = 10

// ---------------------------------------------------------------------------
// Module-level state (not serialisable, lives outside Zustand)
// ---------------------------------------------------------------------------

let refreshTimer: ReturnType<typeof setTimeout> | null = null
let pingTimer: ReturnType<typeof setInterval> | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectCount = 0
let msgCounter = 0

function clearRefreshTimer() {
  if (refreshTimer !== null) { clearTimeout(refreshTimer); refreshTimer = null }
}
function clearPingTimer() {
  if (pingTimer !== null) { clearInterval(pingTimer); pingTimer = null }
}
function clearReconnectTimer() {
  if (reconnectTimer !== null) { clearTimeout(reconnectTimer); reconnectTimer = null }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build the WebSocket URL.
 *  - Vite dev (port 5173) → direct to staging (Vite WS proxy is unreliable)
 *  - Capacitor native (localhost, no port) → direct to staging
 *  - Production web (real domain) → same-origin wss
 */
function buildWsUrl(token: string): string {
  const loc = window.location
  if (loc.hostname === 'localhost') {
    // Both Vite dev (:5173) and Capacitor native (:443) → staging backend
    return `wss://api.staging.myfrya.de/api/v1/chat/stream?token=${token}`
  }
  const proto = loc.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${loc.host}/api/v1/chat/stream?token=${token}`
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

export const useFryaStore = create<FryaStore>((set, get) => {

  // -- Auth helpers --------------------------------------------------------

  function scheduleRefresh(expiresAt: number) {
    clearRefreshTimer()
    const delay = expiresAt - Date.now() - REFRESH_MARGIN_MS
    if (delay <= 0) {
      refreshNow()
      return
    }
    refreshTimer = setTimeout(refreshNow, delay)
  }

  function applyTokens(accessToken: string, refreshTk: string, expiresIn: number) {
    const expiresAt = Date.now() + expiresIn * 1000
    api.setToken(accessToken)
    api.setRefreshToken(refreshTk)
    localStorage.setItem('frya-token', accessToken)
    localStorage.setItem('frya-refresh', refreshTk)
    localStorage.setItem('frya-expires-at', String(expiresAt))
    set({ token: accessToken, refreshToken: refreshTk, expiresAt, isAuthenticated: true })
    scheduleRefresh(expiresAt)
  }

  async function refreshNow() {
    const { refreshToken } = get()
    if (!refreshToken) { get().logout(); return }
    try {
      const newAccessToken = await api.tryRefresh()
      const expiresAt = Date.now() + 3600 * 1000
      localStorage.setItem('frya-token', newAccessToken)
      localStorage.setItem('frya-expires-at', String(expiresAt))
      set({ token: newAccessToken, expiresAt })
      scheduleRefresh(expiresAt)
    } catch {
      // tryRefresh already calls onUnauthorized which triggers logout
    }
  }

  // Register the logout callback with api client (handles refresh failures)
  // P-23: Set session-expired flag so LoginPage shows friendly message
  api.onUnauthorized(() => {
    localStorage.setItem('frya-session-expired', '1')
    get().logout()
  })

  // -- WebSocket helpers ---------------------------------------------------

  function handleWsMessage(raw: string) {
    let msg: WsMessageIncoming
    try { msg = JSON.parse(raw) } catch { return }

    if (msg.type === 'pong') return

    const state = get()

    switch (msg.type) {
      case 'typing':
        set({ isTyping: msg.active, typingHint: msg.hint ?? null })
        break

      case 'chunk': {
        let sid = state.streamingId
        if (!sid) {
          sid = `frya-${++msgCounter}`
          set({
            streamingId: sid,
            messages: [...state.messages, { id: sid, role: 'frya', text: msg.text || '', timestamp: Date.now(), isStreaming: true }],
          })
        } else {
          set({
            messages: state.messages.map(m => m.id === sid ? { ...m, text: m.text + msg.text } : m),
          })
        }
        break
      }

      case 'message_complete': {
        const sid = state.streamingId
        const blocks = Array.isArray(msg.content_blocks) ? msg.content_blocks : []
        const acts = Array.isArray(msg.actions) ? msg.actions : []
        if (sid) {
          set({
            streamingId: null,
            isTyping: false,
            typingHint: null,
            messages: state.messages.map(m =>
              m.id === sid
                ? { ...m, text: msg.text || '', isStreaming: false, suggestions: msg.suggestions, caseRef: msg.case_ref, contextType: msg.context_type, content_blocks: blocks, actions: acts }
                : m,
            ),
          })
        } else {
          const id = `frya-${++msgCounter}`
          set({
            isTyping: false,
            typingHint: null,
            messages: [...state.messages, { id, role: 'frya', text: msg.text || '', timestamp: Date.now(), suggestions: msg.suggestions, caseRef: msg.case_ref, contextType: msg.context_type, content_blocks: blocks, actions: acts }],
          })
        }
        break
      }

      case 'approval_request': {
        const id = `approval-${++msgCounter}`
        set({
          messages: [...state.messages, {
            id, role: 'system', text: '', timestamp: Date.now(),
            approval: { case_id: msg.case_id, case_number: msg.case_number, vendor: msg.vendor, amount: msg.amount, currency: msg.currency, document_type: msg.document_type, buttons: msg.buttons },
          }],
        })
        break
      }

      case 'notification': {
        const id = `notif-${++msgCounter}`
        const updates: Partial<FryaStore> = {
          messages: [...state.messages, { id, role: 'system', text: msg.text || '', timestamp: Date.now(), notificationType: msg.notification_type }],
        }
        // Auto-switch to chat when a document_processed notification arrives
        // so the user sees the new beleg immediately
        if (msg.notification_type === 'document_processed' && state.showGreeting) {
          updates.showGreeting = false
        }
        set(updates)
        break
      }

      case 'duplicate': {
        const id = `dup-${++msgCounter}`
        set({
          messages: [...state.messages, { id, role: 'system', text: '', timestamp: Date.now(), duplicate: { original_title: msg.original_title, paperless_id: msg.paperless_id } }],
        })
        break
      }

      case 'error': {
        const id = `err-${++msgCounter}`
        set({
          isTyping: false,
          typingHint: null,
          streamingId: null,
          messages: [...state.messages, { id, role: 'frya', text: msg.message || 'Ein Fehler ist aufgetreten.', timestamp: Date.now() }],
        })
        break
      }

      case 'ui_hint':
        // reserved for future UI-driven actions
        break

      default: {
        // Unknown message type — NEVER show "Unbekannter Nachrichtentyp" to user.
        // If the message has text, show it. Otherwise ignore silently.
        const raw = msg as any
        if (raw.text || raw.reply || raw.message) {
          const id = `unknown-${++msgCounter}`
          set({
            isTyping: false,
            messages: [...state.messages, {
              id, role: 'frya',
              text: raw.text || raw.reply || raw.message || '',
              timestamp: Date.now(),
              content_blocks: Array.isArray(raw.content_blocks) ? raw.content_blocks : [],
              actions: Array.isArray(raw.actions) ? raw.actions : [],
            }],
          })
        }
        break
      }
    }
  }

  function connectWs() {
    const { token } = get()
    if (!token) return

    // Clean up previous socket
    const prev = get().ws
    if (prev) { prev.onclose = null; prev.close() }
    clearPingTimer()

    const ws = new WebSocket(buildWsUrl(token))
    set({ ws })

    ws.onopen = () => {
      set({ wsConnected: true })
      reconnectCount = 0
      // Heartbeat ping
      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = (event) => { handleWsMessage(event.data as string) }

    ws.onclose = (event) => {
      set({ wsConnected: false, ws: null })
      clearPingTimer()
      // P-23: On 4001/4003 (token expired) or generic close — refresh token first, then reconnect
      if (!get().isAuthenticated) return
      if (reconnectCount >= WS_MAX_RETRIES) return

      reconnectCount++
      const isTokenError = event.code === 4001 || event.code === 4003 || event.code === 1008 || event.code === 403
      if (isTokenError) {
        // Token expired — refresh first, then reconnect with new token
        refreshNow().then(() => {
          if (get().isAuthenticated) {
            reconnectTimer = setTimeout(() => { connectWs() }, 500)
          }
        }).catch(() => { /* refreshNow handles logout */ })
      } else {
        // Normal reconnect (network glitch etc.) with exponential backoff
        const delay = Math.min(WS_RECONNECT_DELAY_MS * Math.pow(1.5, reconnectCount - 1), 30_000)
        reconnectTimer = setTimeout(() => { connectWs() }, delay)
      }
    }

    ws.onerror = () => { /* onclose will fire after onerror */ }
  }

  // -- Return store --------------------------------------------------------

  return {
    // Auth state
    token: null,
    refreshToken: null,
    expiresAt: null,
    isAuthenticated: false,
    isRestored: false,

    login: async (email, password) => {
      const data = await api.post<LoginResponse>('/auth/login', { email, password })
      // Persist email for Settings display + Google Password Manager
      localStorage.setItem('frya-email', email)
      applyTokens(data.access_token, data.refresh_token, data.expires_in)
      // Auto-connect WS after login
      setTimeout(() => { get().connect() }, 0)
    },

    logout: () => {
      clearRefreshTimer()
      clearPingTimer()
      clearReconnectTimer()
      const ws = get().ws
      if (ws) { ws.onclose = null; ws.close() }
      api.setToken(null)
      api.setRefreshToken(null)
      localStorage.removeItem('frya-token')
      localStorage.removeItem('frya-refresh')
      localStorage.removeItem('frya-expires-at')
      set({
        token: null, refreshToken: null, expiresAt: null, isAuthenticated: false,
        ws: null, wsConnected: false,
        messages: [], isTyping: false, typingHint: null, streamingId: null,
        showGreeting: true,
      })
    },

    restore: () => {
      const token = localStorage.getItem('frya-token')
      const refresh = localStorage.getItem('frya-refresh')
      const expiresAtStr = localStorage.getItem('frya-expires-at')
      const expiresAt = expiresAtStr ? Number(expiresAtStr) : null

      if (token && refresh) {
        api.setToken(token)
        api.setRefreshToken(refresh)
        set({ token, refreshToken: refresh, expiresAt, isAuthenticated: true, isRestored: true })
        if (expiresAt) scheduleRefresh(expiresAt)
        // Auto-connect WS on restore
        setTimeout(() => { get().connect() }, 0)
      } else {
        set({ isRestored: true })
      }
    },

    // UI
    showGreeting: true,
    showSettings: false,
    pdfViewer: null,

    startChat: (initialMessage?: string) => {
      set({ showGreeting: false, showSettings: false })
      if (initialMessage) {
        // Show user message in chat immediately
        get().addUserMessage(initialMessage)
        // Slight delay so the ChatView mounts and WS is ready
        setTimeout(() => { get().send({ type: 'message', text: initialMessage }) }, 100)
      }
    },

    goHome: () => {
      set({ showGreeting: true, showSettings: false })
    },

    openSettings: () => {
      set({ showSettings: true, showGreeting: false })
    },

    openPdfViewer: (caseId: string, title: string) => {
      set({ pdfViewer: { caseId, title } })
    },

    closePdfViewer: () => {
      set({ pdfViewer: null })
    },

    // Chat state
    messages: [],
    isTyping: false,
    typingHint: null,
    streamingId: null,

    addUserMessage: (text) => {
      const id = `user-${++msgCounter}`
      set(s => ({ messages: [...s.messages, { id, role: 'user', text, timestamp: Date.now() }] }))
    },

    addFryaMessage: (msg) => {
      const id = `frya-${++msgCounter}`
      set(s => ({
        messages: [...s.messages, {
          id, role: 'frya', text: msg.text, timestamp: Date.now(),
          content_blocks: msg.content_blocks, actions: msg.actions,
        }],
      }))
    },

    setTyping: (active, hint) => set({ isTyping: active, typingHint: hint ?? null }),

    addApprovalRequest: (data) => {
      const id = `approval-${++msgCounter}`
      set(s => ({ messages: [...s.messages, { id, role: 'system', text: '', timestamp: Date.now(), approval: data }] }))
    },

    addNotification: (text, notificationType) => {
      const id = `notif-${++msgCounter}`
      set(s => ({ messages: [...s.messages, { id, role: 'system', text, timestamp: Date.now(), notificationType }] }))
    },

    addDuplicate: (data) => {
      const id = `dup-${++msgCounter}`
      set(s => ({ messages: [...s.messages, { id, role: 'system', text: '', timestamp: Date.now(), duplicate: data }] }))
    },

    setApprovalAction: (messageId, action) => {
      set(s => ({ messages: s.messages.map(m => m.id === messageId ? { ...m, approvalAction: action } : m) }))
    },

    clearChat: () => set({ messages: [], isTyping: false, typingHint: null, streamingId: null }),

    // WebSocket state
    ws: null,
    wsConnected: false,

    connect: () => {
      reconnectCount = 0
      connectWs()
    },

    disconnect: () => {
      clearPingTimer()
      clearReconnectTimer()
      const ws = get().ws
      if (ws) { ws.onclose = null; ws.close() }
      set({ ws: null, wsConnected: false })
    },

    send: (msg: any) => {
      const { ws } = get()
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(msg))
      } else {
        // Fallback: REST endpoint for text messages
        if (msg.type === 'message' && msg.text) {
          api.post<{ reply: string; case_ref: string | null; suggestions: string[] }>('/chat', { message: msg.text })
            .then(res => {
              handleWsMessage(JSON.stringify({
                type: 'message_complete',
                text: res.reply,
                case_ref: res.case_ref,
                suggestions: res.suggestions || [],
              }))
            })
            .catch(err => {
              handleWsMessage(JSON.stringify({ type: 'error', message: err.message || 'Verbindungsfehler' }))
            })
        }
      }
    },

    sendAction: (action: any) => {
      const { ws, addUserMessage } = get()
      // Show action text as user message
      if (action.chat_text) addUserMessage(action.chat_text)
      if (ws && ws.readyState === WebSocket.OPEN) {
        // Send as 'message' with quick_action — NOT as 'action' type
        ws.send(JSON.stringify({
          type: 'message',
          text: action.chat_text || action.label || '',
          quick_action: action.quick_action || undefined,
        }))
      }
    },

    submitForm: (formId: string, formType: string, data: any) => {
      const { ws } = get()
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'form_submit', form_id: formId, form_type: formType, data }))
      }
    },
  }
})
