import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''

  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError('Das Passwort muss mindestens 8 Zeichen lang sein.')
      return
    }
    if (password !== passwordConfirm) {
      setError('Die Passwoerter stimmen nicht ueberein.')
      return
    }
    if (!token) {
      setError('Link ungueltig oder abgelaufen.')
      return
    }

    setLoading(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setSuccess(true)
    } catch {
      setError('Link ungueltig oder abgelaufen.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface p-4">
      <div className="w-full max-w-sm bg-surface-container rounded-m3-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-display font-bold text-primary mb-2">FRYA</h1>
          <p className="text-on-surface-variant text-sm">Neues Passwort setzen</p>
        </div>

        {success ? (
          <div className="text-center">
            <p className="text-on-surface text-sm mb-6">
              Passwort wurde geaendert.
            </p>
            <a
              href="/login"
              className="text-sm text-primary hover:underline"
            >
              Zum Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1">
                Neues Passwort
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors"
                placeholder="Mindestens 8 Zeichen"
                required
                minLength={8}
                autoFocus
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1">
                Passwort bestaetigen
              </label>
              <input
                type="password"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors"
                placeholder="Passwort wiederholen"
                required
                minLength={8}
              />
            </div>

            {error && (
              <p className="text-error text-sm text-center">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 bg-primary text-on-primary rounded-m3-xl font-semibold text-sm mt-2 disabled:opacity-50 transition-opacity"
            >
              {loading ? 'Wird gespeichert...' : 'Passwort setzen'}
            </button>

            <div className="text-center mt-2">
              <a
                href="/login"
                className="text-sm text-primary hover:underline"
              >
                Zurueck zum Login
              </a>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
