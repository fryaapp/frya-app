/** API base URL — proxied by Vite in dev, same-origin in prod */
export const API_BASE = '/api/v1'

/** WebSocket URL */
export const WS_BASE = import.meta.env.DEV
  ? `ws://${window.location.host}/api/v1`
  : `wss://${window.location.host}/api/v1`
