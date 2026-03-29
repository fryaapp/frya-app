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
      setError('Anfrage konnte nicht gesendet werden. Bitte erneut versuchen.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="flex items-center justify-center min-h-screen p-4"
      style={{ background: 'var(--frya-page-bg)' }}
    >
      <div
        aria-hidden
        style={{
          position: 'fixed', top: '-120px', left: '50%', transform: 'translateX(-50%)',
          width: '700px', height: '500px',
          background: 'radial-gradient(ellipse at 50% 20%, rgba(240,138,58,0.22) 0%, rgba(240,138,58,0.06) 40%, transparent 70%)',
          pointerEvents: 'none', filter: 'blur(30px)',
        }}
      />

      <div
        className="w-full max-w-sm animate-slide-up"
        style={{
          background: 'linear-gradient(170deg, var(--frya-surface-container-high) 0%, var(--frya-surface-container-low) 100%)',
          borderRadius: 32, padding: '44px 32px 40px',
          boxShadow: '0 8px 40px rgba(0,0,0,0.6), 0 0 80px rgba(240,138,58,0.06)',
          border: '1px solid rgba(240,138,58,0.08)', position: 'relative',
        }}
      >
        <div aria-hidden style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: '200px', height: '2px', borderRadius: '2px', background: 'linear-gradient(90deg, transparent, var(--frya-primary), transparent)', opacity: 0.5 }} />
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div
            style={{
              width: 64, height: 64, borderRadius: 22,
              background: 'linear-gradient(135deg, var(--frya-primary) 0%, var(--frya-primary-container) 100%)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 18px',
              boxShadow: '0 4px 20px rgba(240,138,58,0.3)',
            }}
          >
            <span
              className="material-symbols-rounded"
              style={{ fontSize: 30, color: '#fff', fontVariationSettings: "'FILL' 1" }}
            >
              lock_reset
            </span>
          </div>
          <h1 style={{ fontFamily: 'Outfit, sans-serif', fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--frya-on-surface)', marginBottom: 6 }}>
            Passwort zurücksetzen
          </h1>
          <p style={{ color: 'var(--frya-on-surface-variant)', fontSize: 13 }}>
            Wir schicken dir einen Link per E-Mail
          </p>
        </div>

        {sent ? (
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                background: 'var(--frya-surface-container-high)',
                borderRadius: 16, padding: '16px',
                fontSize: 14, color: 'var(--frya-on-surface-variant)',
                lineHeight: 1.6, marginBottom: 24,
                display: 'flex', alignItems: 'flex-start', gap: 10, textAlign: 'left',
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 18, color: 'var(--frya-info)', flexShrink: 0, marginTop: 2 }}>info</span>
              Falls ein Konto mit dieser E-Mail existiert, wurde ein Reset-Link gesendet. Bitte auch den Spam-Ordner prüfen.
            </div>
            <a
              href="/login"
              style={{ fontSize: 13, color: 'var(--frya-primary)', textDecoration: 'none' }}
              onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'underline')}
              onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'none')}
            >
              ← Zurück zum Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="E-Mail-Adresse"
                required
                autoFocus
                style={{
                  width: '100%',
                  paddingLeft: 44, paddingRight: 20, paddingTop: 14, paddingBottom: 14,
                  background: 'var(--frya-surface-container-high)',
                  border: 'none', borderRadius: 28,
                  fontSize: 14, color: 'var(--frya-on-surface)', fontFamily: 'inherit',
                  outline: 'none', transition: 'box-shadow 0.2s',
                }}
                onFocus={(e) => (e.target.style.boxShadow = '0 0 0 2px var(--frya-primary)')}
                onBlur={(e) => (e.target.style.boxShadow = 'none')}
              />
            </div>

            {error && (
              <div
                style={{
                  background: 'var(--frya-error-container)', borderRadius: 12,
                  padding: '10px 16px', fontSize: 13, color: 'var(--frya-error)',
                  display: 'flex', alignItems: 'center', gap: 8,
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>error</span>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{
                marginTop: 6, width: '100%', padding: '16px 20px',
                background: loading ? 'var(--frya-surface-container-high)' : 'linear-gradient(135deg, var(--frya-primary) 0%, #D4722A 100%)',
                color: loading ? 'var(--frya-on-surface-variant)' : '#fff',
                border: 'none', borderRadius: 28,
                fontFamily: 'Outfit, sans-serif', fontSize: 15, fontWeight: 700, letterSpacing: '0.02em',
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'all 0.25s ease',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                boxShadow: loading ? 'none' : '0 4px 16px rgba(240,138,58,0.35)',
              }}
            >
              {loading ? (
                <>
                  <span className="material-symbols-rounded" style={{ fontSize: 16 }}>hourglass_empty</span>
                  Wird gesendet…
                </>
              ) : (
                <>
                  <span className="material-symbols-rounded" style={{ fontSize: 16 }}>send</span>
                  Link senden
                </>
              )}
            </button>

            <div style={{ textAlign: 'center', marginTop: 4 }}>
              <a
                href="/login"
                style={{ fontSize: 13, color: 'var(--frya-primary)', textDecoration: 'none' }}
                onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'underline')}
                onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'none')}
              >
                ← Zurück zum Login
              </a>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
