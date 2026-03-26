import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const login = useAuthStore((s) => s.login)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/')
    } catch {
      setError('E-Mail oder Passwort falsch.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface p-4">
      <div className="w-full max-w-sm bg-surface-container rounded-m3-lg p-8">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-display font-bold text-primary mb-2">FRYA</h1>
          <p className="text-on-surface-variant text-sm">Deine KI-Buchhaltungsassistentin</p>
        </div>

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

          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1">
              Passwort
            </label>
            <div className="relative">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 pr-12 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors"
                placeholder="Passwort"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors"
                aria-label={showPassword ? 'Passwort verbergen' : 'Passwort anzeigen'}
              >
                <span className="material-symbols-outlined text-xl">
                  {showPassword ? 'visibility_off' : 'visibility'}
                </span>
              </button>
            </div>
          </div>

          {error && (
            <p className="text-error text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-primary text-on-primary rounded-m3-xl font-semibold text-sm mt-2 disabled:opacity-50 transition-opacity"
          >
            {loading ? 'Anmelden...' : 'Anmelden'}
          </button>

          <div className="text-center mt-2">
            <a
              href="/forgot-password"
              className="text-sm text-primary hover:underline"
            >
              Passwort vergessen?
            </a>
          </div>
        </form>
      </div>
    </div>
  )
}
