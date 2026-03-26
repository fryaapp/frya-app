import { useState } from 'react'
import { api } from '../lib/api'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch {
      setError('Anfrage konnte nicht gesendet werden. Bitte versuchen Sie es erneut.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface p-4">
      <div className="w-full max-w-sm bg-surface-container rounded-m3-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-display font-bold text-primary mb-2">FRYA</h1>
          <p className="text-on-surface-variant text-sm">Passwort vergessen</p>
        </div>

        {sent ? (
          <div className="text-center">
            <p className="text-on-surface text-sm mb-6">
              Falls ein Konto existiert, wurde eine E-Mail gesendet.
            </p>
            <a
              href="/login"
              className="text-sm text-primary hover:underline"
            >
              Zurueck zum Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1">
                E-Mail
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors"
                placeholder="name@beispiel.de"
                required
                autoFocus
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
              {loading ? 'Wird gesendet...' : 'Link senden'}
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
