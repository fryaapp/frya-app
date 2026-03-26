import { API_BASE } from './constants'

type UnauthorizedCallback = () => void

class ApiClient {
  private token: string | null = null
  private refreshToken: string | null = null
  private refreshPromise: Promise<string> | null = null
  private onUnauthorizedCb: UnauthorizedCallback | null = null

  setToken(token: string | null) {
    this.token = token
  }

  setRefreshToken(refreshToken: string | null) {
    this.refreshToken = refreshToken
  }

  /** Register a callback invoked when refresh fails (i.e. full logout needed). */
  onUnauthorized(cb: UnauthorizedCallback) {
    this.onUnauthorizedCb = cb
  }

  /**
   * Attempt to refresh the access token.
   * Deduplicates concurrent calls — only one refresh runs at a time.
   */
  async tryRefresh(): Promise<string> {
    if (this.refreshPromise) return this.refreshPromise

    this.refreshPromise = (async () => {
      try {
        if (!this.refreshToken) throw new Error('No refresh token')

        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: this.refreshToken }),
        })

        if (!res.ok) throw new ApiError(res.status, await res.text())

        const data: { access_token: string; refresh_token?: string; expires_in?: number } =
          await res.json()

        this.token = data.access_token
        if (data.refresh_token) this.refreshToken = data.refresh_token

        return data.access_token
      } catch {
        this.onUnauthorizedCb?.()
        throw new ApiError(401, 'Token refresh failed')
      } finally {
        this.refreshPromise = null
      }
    })()

    return this.refreshPromise
  }

  private headers(extra?: Record<string, string>): Record<string, string> {
    const h: Record<string, string> = { 'Content-Type': 'application/json', ...extra }
    if (this.token) h['Authorization'] = `Bearer ${this.token}`
    return h
  }

  private authHeaders(): Record<string, string> {
    const h: Record<string, string> = {}
    if (this.token) h['Authorization'] = `Bearer ${this.token}`
    return h
  }

  /**
   * Core request handler with 401 retry.
   * On 401: refresh token, then retry the request exactly once.
   */
  private async request<T>(
    url: string,
    init: RequestInit,
    parseResponse: (res: Response) => Promise<T>,
  ): Promise<T> {
    const doFetch = async (): Promise<Response> => {
      // Rebuild auth header with current token
      const headers = new Headers(init.headers)
      if (this.token) headers.set('Authorization', `Bearer ${this.token}`)
      return fetch(url, { ...init, headers })
    }

    let res = await doFetch()

    if (res.status === 401 && this.refreshToken) {
      try {
        await this.tryRefresh()
        res = await doFetch()
      } catch {
        // Refresh failed — onUnauthorizedCb already called inside tryRefresh
        throw new ApiError(401, 'Unauthorized')
      }
    }

    if (!res.ok) throw new ApiError(res.status, await res.text())
    return parseResponse(res)
  }

  async get<T = unknown>(path: string): Promise<T> {
    return this.request<T>(
      `${API_BASE}${path}`,
      { headers: this.headers() },
      (r) => r.json(),
    )
  }

  async post<T = unknown>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(
      `${API_BASE}${path}`,
      {
        method: 'POST',
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
      },
      (r) => r.json(),
    )
  }

  async put<T = unknown>(path: string, body?: unknown): Promise<T> {
    return this.request<T>(
      `${API_BASE}${path}`,
      {
        method: 'PUT',
        headers: this.headers(),
        body: body ? JSON.stringify(body) : undefined,
      },
      (r) => r.json(),
    )
  }

  async postFormData<T = unknown>(path: string, formData: FormData): Promise<T> {
    return this.request<T>(
      `${API_BASE}${path}`,
      { method: 'POST', headers: this.authHeaders(), body: formData },
      (r) => r.json(),
    )
  }

  async getBlob(path: string): Promise<Blob> {
    return this.request<Blob>(
      `${API_BASE}${path}`,
      { headers: this.authHeaders() },
      (r) => r.blob(),
    )
  }

  async upload<T = unknown>(path: string, file: File): Promise<T> {
    const form = new FormData()
    form.append('file', file)
    return this.request<T>(
      `${API_BASE}${path}`,
      { method: 'POST', headers: this.authHeaders(), body: form },
      (r) => r.json(),
    )
  }

  async bulkUpload<T = unknown>(path: string, files: File[]): Promise<T> {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return this.request<T>(
      `${API_BASE}${path}`,
      { method: 'POST', headers: this.authHeaders(), body: form },
      (r) => r.json(),
    )
  }
}

export class ApiError extends Error {
  status: number
  body: string
  constructor(status: number, body: string) {
    super(`HTTP ${status}`)
    this.status = status
    this.body = body
  }
}

export const api = new ApiClient()
