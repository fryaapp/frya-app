import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  // P-23: Show session-expired message if user was auto-logged-out
  const [sessionExpired] = useState(() => {
    const flag = localStorage.getItem('frya-session-expired')
    if (flag) localStorage.removeItem('frya-session-expired')
    return !!flag
  })
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
    <div
      className="flex items-center justify-center min-h-screen p-4"
      style={{
        background: 'var(--frya-page-bg)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Layered ambient glow */}
      <div
        aria-hidden
        style={{
          position: 'fixed', top: '-120px', left: '50%', transform: 'translateX(-50%)',
          width: '700px', height: '500px',
          background: 'radial-gradient(ellipse at 50% 20%, rgba(240,138,58,0.22) 0%, rgba(240,138,58,0.06) 40%, transparent 70%)',
          pointerEvents: 'none',
          filter: 'blur(30px)',
        }}
      />
      {/* Secondary warm ring */}
      <div
        aria-hidden
        style={{
          position: 'fixed', top: '40px', left: '50%', transform: 'translateX(-50%)',
          width: '300px', height: '300px',
          background: 'radial-gradient(circle, rgba(240,138,58,0.15) 0%, transparent 60%)',
          pointerEvents: 'none',
        }}
      />

      <div
        className="w-full max-w-sm animate-slide-up"
        style={{
          background: 'linear-gradient(170deg, var(--frya-surface-container-high) 0%, var(--frya-surface-container-low) 100%)',
          borderRadius: '32px',
          padding: '44px 32px 40px',
          boxShadow: '0 8px 40px rgba(0,0,0,0.6), 0 0 80px rgba(240,138,58,0.06)',
          border: '1px solid rgba(240,138,58,0.08)',
          position: 'relative',
        }}
      >
        {/* Subtle inner glow at top of card */}
        <div
          aria-hidden
          style={{
            position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)',
            width: '200px', height: '2px', borderRadius: '2px',
            background: 'linear-gradient(90deg, transparent, var(--frya-primary), transparent)',
            opacity: 0.5,
          }}
        />

        {/* Banner Logo */}
        <div className="text-center mb-8">
          <img
            src="/frya-banner.png"
            alt="FRYA — Belege rein. Kopf frei."
            style={{
              width: '100%',
              maxWidth: '320px',
              height: 'auto',
              margin: '0 auto 12px',
              display: 'block',
              filter: 'drop-shadow(0 4px 20px rgba(240,138,58,0.2))',
            }}
          />
          <p style={{ color: 'var(--frya-on-surface-variant)', fontSize: 13, letterSpacing: '0.01em' }}>
            Deine KI-Buchhaltungsassistentin
          </p>
        </div>

        {/* P-23: Session expired info banner */}
        {sessionExpired && !error && (
          <div
            style={{
              background: 'rgba(240,138,58,0.12)',
              borderRadius: 14,
              padding: '11px 16px',
              fontSize: 13,
              color: 'var(--frya-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 4,
            }}
          >
            <span className="material-symbols-rounded" style={{ fontSize: 16 }}>schedule</span>
            Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.
          </div>
        )}

        <form onSubmit={handleSubmit} autoComplete="on" method="post" action="#" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* E-Mail */}
          <div style={{ position: 'relative' }}>
            <span
              className="material-symbols-rounded"
              style={{
                position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)',
                fontSize: 18, color: 'var(--frya-on-surface-variant)', pointerEvents: 'none',
              }}
            >
              mail
            </span>
            <input
              type="email"
              id="frya-email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="E-Mail"
              required
              autoFocus
              style={{
                width: '100%',
                paddingLeft: 46, paddingRight: 20, paddingTop: 15, paddingBottom: 15,
                background: 'var(--frya-surface-container-lowest)',
                border: '1px solid var(--frya-outline-variant)',
                borderRadius: 28,
                fontSize: 14, color: 'var(--frya-on-surface)', fontFamily: 'inherit',
                outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = 'var(--frya-primary)'
                e.target.style.boxShadow = '0 0 0 3px rgba(240,138,58,0.15)'
              }}
              onBlur={(e) => {
                e.target.style.borderColor = 'var(--frya-outline-variant)'
                e.target.style.boxShadow = 'none'
              }}
            />
          </div>

          {/* Passwort */}
          <div style={{ position: 'relative' }}>
            <span
              className="material-symbols-rounded"
              style={{
                position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)',
                fontSize: 18, color: 'var(--frya-on-surface-variant)', pointerEvents: 'none',
              }}
            >
              lock
            </span>
            <input
              type={showPassword ? 'text' : 'password'}
              id="frya-password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Passwort"
              required
              style={{
                width: '100%',
                paddingLeft: 46, paddingRight: 50, paddingTop: 15, paddingBottom: 15,
                background: 'var(--frya-surface-container-lowest)',
                border: '1px solid var(--frya-outline-variant)',
                borderRadius: 28,
                fontSize: 14, color: 'var(--frya-on-surface)', fontFamily: 'inherit',
                outline: 'none', transition: 'all 0.2s',
              }}
              onFocus={(e) => {
                e.target.style.borderColor = 'var(--frya-primary)'
                e.target.style.boxShadow = '0 0 0 3px rgba(240,138,58,0.15)'
              }}
              onBlur={(e) => {
                e.target.style.borderColor = 'var(--frya-outline-variant)'
                e.target.style.boxShadow = 'none'
              }}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? 'Passwort verbergen' : 'Passwort anzeigen'}
              style={{
                position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--frya-on-surface-variant)', display: 'flex', alignItems: 'center', padding: 4,
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 18 }}>
                {showPassword ? 'visibility_off' : 'visibility'}
              </span>
            </button>
          </div>

          {error && (
            <div
              style={{
                background: 'var(--frya-error-container)',
                borderRadius: 14,
                padding: '11px 16px',
                fontSize: 13,
                color: 'var(--frya-error)',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 16, fontVariationSettings: "'FILL' 1" }}>error</span>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              marginTop: 6,
              width: '100%',
              padding: '16px 20px',
              background: loading
                ? 'var(--frya-surface-container-high)'
                : 'linear-gradient(135deg, var(--frya-primary) 0%, #D4722A 100%)',
              color: loading ? 'var(--frya-on-surface-variant)' : '#fff',
              border: 'none',
              borderRadius: 28,
              fontFamily: 'Outfit, sans-serif',
              fontSize: 15,
              fontWeight: 700,
              letterSpacing: '0.02em',
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'all 0.25s ease',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              boxShadow: loading ? 'none' : '0 4px 16px rgba(240,138,58,0.35)',
            }}
            onMouseEnter={(e) => {
              if (!loading) (e.target as HTMLButtonElement).style.boxShadow = '0 6px 24px rgba(240,138,58,0.5)'
            }}
            onMouseLeave={(e) => {
              if (!loading) (e.target as HTMLButtonElement).style.boxShadow = '0 4px 16px rgba(240,138,58,0.35)'
            }}
          >
            {loading ? (
              <>
                <span className="material-symbols-rounded animate-pulse-dot" style={{ fontSize: 16 }}>
                  hourglass_empty
                </span>
                Anmelden...
              </>
            ) : (
              <>
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>login</span>
                Anmelden
              </>
            )}
          </button>

          <div style={{ textAlign: 'center', marginTop: 6 }}>
            <a
              href="/forgot-password"
              style={{ fontSize: 13, color: 'var(--frya-primary)', textDecoration: 'none', transition: 'opacity 0.2s' }}
              onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.opacity = '0.7')}
              onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.opacity = '1')}
            >
              Passwort vergessen?
            </a>
          </div>
        </form>
      </div>
    </div>
  )
}
