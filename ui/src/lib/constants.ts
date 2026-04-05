/** Staging API root — used by Capacitor native builds and Vite dev proxy */
const STAGING_API = 'https://api.staging.myfrya.de'

/**
 * Detect Capacitor native context:
 *  - hostname is 'localhost' (Capacitor internal server)
 *  - port is '' (default HTTPS 443, NOT Vite's explicit :5173)
 */
const isCapacitorNative =
  typeof window !== 'undefined' &&
  window.location.hostname === 'localhost' &&
  window.location.port === ''

/** API base URL — full URL in Capacitor, proxied relative path in Vite dev, same-origin in prod */
export const API_BASE = isCapacitorNative
  ? `${STAGING_API}/api/v1`
  : '/api/v1'

/** WebSocket URL */
export const WS_BASE = isCapacitorNative
  ? `wss://api.staging.myfrya.de/api/v1`
  : import.meta.env.DEV
    ? `ws://${window.location.host}/api/v1`
    : `wss://${window.location.host}/api/v1`
