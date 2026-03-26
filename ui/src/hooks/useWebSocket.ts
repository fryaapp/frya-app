import { useEffect, useRef, useCallback, useState } from 'react'
import { useAuthStore } from '../stores/authStore'
import { WS_BASE } from '../lib/constants'

export type WsMessage =
  | { type: 'pong' }
  | { type: 'typing'; active: boolean; hint?: string }
  | { type: 'chunk'; text: string }
  | { type: 'message_complete'; text: string; case_ref: string | null; suggestions: string[]; context_type?: string }
  | { type: 'approval_request'; case_id: string; case_number?: string; vendor: string; amount: number; currency?: string; buttons: string[]; document_type?: string }
  | { type: 'notification'; text: string; notification_type: string }
  | { type: 'duplicate'; original_title: string; paperless_id: number }
  | { type: 'ui_hint'; action: string; context_type?: string }
  | { type: 'error'; message: string }

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000
const PING_INTERVAL = 30_000

export function useWebSocket(onMessage: (msg: WsMessage) => void) {
  const token = useAuthStore((s) => s.token)
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const reconnectAttempt = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pingTimer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!token || !mountedRef.current) return

    // Clean up previous
    if (wsRef.current) {
      wsRef.current.onclose = null
      wsRef.current.close()
    }
    if (pingTimer.current) clearInterval(pingTimer.current)

    const ws = new WebSocket(`${WS_BASE}/chat/stream?token=${token}`)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return }
      setConnected(true)
      reconnectAttempt.current = 0

      // Heartbeat
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as WsMessage
        if (msg.type !== 'pong') {
          onMessageRef.current(msg)
        }
      } catch {
        console.warn('WS parse error')
      }
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setConnected(false)
      if (pingTimer.current) clearInterval(pingTimer.current)

      // Exponential backoff reconnect
      const delay = Math.min(
        INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempt.current),
        MAX_RECONNECT_DELAY,
      )
      reconnectAttempt.current++
      reconnectTimer.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }, [token])

  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (pingTimer.current) clearInterval(pingTimer.current)
      if (wsRef.current) {
        wsRef.current.onclose = null
        wsRef.current.close()
      }
      wsRef.current = null
    }
  }, [connect])

  const send = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'message', text }))
    }
  }, [])

  const sendFile = useCallback((file: File) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // File uploads go through REST, not WS — but we notify WS about intent
      wsRef.current.send(JSON.stringify({ type: 'file_uploaded', filename: file.name }))
    }
  }, [])

  return { send, sendFile, connected }
}
