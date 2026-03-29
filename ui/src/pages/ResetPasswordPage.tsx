import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'

const inputStyle = {
  width: '100%',
  paddingLeft: 44, paddingRight: 20, paddingTop: 14, paddingBottom: 14,
  background: 'var(--frya-surface-container-high)',
  border: 'none', borderRadius: 28,
  fontSize: 14, color: 'var(--frya-on-surface)', fontFamily: 'inherit',
  outline: 'none', transition: 'box-shadow 0.2s',
}

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const isFirstLogin = searchParams.get('first') === 'true'

  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (password.length < 8) { setError('Mindestens 8 Zeichen erforderlich.'); return }
    if (password !== passwordConfirm) { setError('Die Passwörter stimmen nicht überein.'); return }
    if (!token) { setError('Link ungültig oder abgelaufen.'); return }
    setLoading(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setSuccess(true)
    } catch {
      setError('Link ungültig oder abgelaufen.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen p-4" style={{ background: 'var(--frya-page-bg)' }}>
      <div aria-hidden style={{ position: 'fixed', top: '-120px', left: '50%', transform: 'translateX(-50%)', width: '700px', height: '500px', background: 'radial-gradient(ellipse at 50% 20%, rgba(240,138,58,0.22) 0%, rgba(240,138,58,0.06) 40%, transparent 70%)', pointerEvents: 'none', filter: 'blur(30px)' }} />

      <div className="w-full max-w-sm animate-slide-up" style={{ background: 'linear-gradient(170deg, var(--frya-surface-container-high) 0%, var(--frya-surface-container-low) 100%)', borderRadius: 32, padding: '44px 32px 40px', boxShadow: '0 8px 40px rgba(0,0,0,0.6), 0 0 80px rgba(240,138,58,0.06)', border: '1px solid rgba(240,138,58,0.08)', position: 'relative' }}>
        <div aria-hidden style={{ position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)', width: '200px', height: '2px', borderRadius: '2px', background: 'linear-gradient(90deg, transparent, var(--frya-primary), transparent)', opacity: 0.5 }} />
        {/* Icon + Title */}
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ width: 64, height: 64, borderRadius: 22, background: 'linear-gradient(135deg, var(--frya-primary) 0%, var(--frya-primary-container) 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 18px', boxShadow: '0 4px 20px rgba(240,138,58,0.3)' }}>
            <span className="material-symbols-rounded" style={{ fontSize: 30, color: '#fff', fontVariationSettings: "'FILL' 1" }}>
              {isFirstLogin ? 'person' : 'key'}
            </span>
          </div>
          <h1 style={{ fontFamily: 'Outfit, sans-serif', fontSize: 26, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--frya-on-surface)', marginBottom: 6 }}>
            {isFirstLogin ? 'Konto einrichten' : 'Neues Passwort'}
          </h1>
          <p style={{ color: 'var(--frya-on-surface-variant)', fontSize: 13 }}>
            {isFirstLogin ? 'Wähle ein sicheres Passwort für deinen Zugang' : 'Bitte wähle ein neues Passwort'}
          </p>
        </div>

        {success ? (
          <div style={{ textAlign: 'center' }}>
            <div style={{ background: 'var(--frya-success-container)', borderRadius: 16, padding: '14px 16px', fontSize: 14, color: 'var(--frya-success)', display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24, textAlign: 'left' }}>
              <span className="material-symbols-rounded" style={{ fontSize: 18, flexShrink: 0, fontVariationSettings: "'FILL' 1" }}>check_circle</span>
              Passwort wurde erfolgreich gesetzt.
            </div>
            <a href="/login" style={{ fontSize: 13, color: 'var(--frya-primary)', textDecoration: 'none' }}
              onMouseEnter={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'underline')}
              onMouseLeave={(e) => ((e.target as HTMLAnchorElement).style.textDecoration = 'none')}
            >
              Jetzt anmelden →
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* Password */}
            <div style={{ position: 'relative' }}>
              <span className="material-symbols-rounded" style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)', fontSize: 18, color: 'var(--frya-on-surface-variant)', pointerEvents: 'none' }}>lock</span>
              <input type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                placeholder="Neues Passwort" required minLength={8} autoFocus style={{ ...inputStyle, paddingRight: 48 }}
                onFocus={(e) => (e.target.style.boxShadow = '0 0 0 2px var(--frya-primary)')}
                onBlur={(e) => (e.target.style.boxShadow = 'none')} />
              <button type="button" onClick={() => setShowPw(v => !v)} style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--frya-on-surface-variant)', display: 'flex', padding: 4 }}>
                <span className="material-symbols-rounded" style={{ fontSize: 18 }}>{showPw ? 'visibility_off' : 'visibility'}</span>
              </button>
            </div>

            {/* Confirm */}
            <div style={{ position: 'relative' }}>
              <span className="material-symbols-rounded" style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)', fontSize: 18, color: 'var(--frya-on-surface-variant)', pointerEvents: 'none' }}>lock_clock</span>
              <input type={showPw ? 'text' : 'password'} value={passwordConfirm} onChange={(e) => setPasswordConfirm(e.target.value)}
                placeholder="Passwort wiederholen" required minLength={8} style={inputStyle}
                onFocus={(e) => (e.target.style.boxShadow = '0 0 0 2px var(--frya-primary)')}
                onBlur={(e) => (e.target.style.boxShadow = 'none')} />
            </div>

            {/* Password strength hint */}
            {password.length > 0 && password.length < 8 && (
              <p style={{ fontSize: 12, color: 'var(--frya-on-surface-variant)', paddingLeft: 4 }}>
                Noch {8 - password.length} Zeichen
              </p>
            )}

            {error && (
              <div style={{ background: 'var(--frya-error-container)', borderRadius: 12, padding: '10px 16px', fontSize: 13, color: 'var(--frya-error)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>error</span>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} style={{ marginTop: 6, width: '100%', padding: '16px 20px', background: loading ? 'var(--frya-surface-container-high)' : 'linear-gradient(135deg, var(--frya-primary) 0%, #D4722A 100%)', color: loading ? 'var(--frya-on-surface-variant)' : '#fff', border: 'none', borderRadius: 28, fontFamily: 'Outfit, sans-serif', fontSize: 15, fontWeight: 700, letterSpacing: '0.02em', cursor: loading ? 'not-allowed' : 'pointer', transition: 'all 0.25s ease', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, boxShadow: loading ? 'none' : '0 4px 16px rgba(240,138,58,0.35)' }}>
              {loading ? (
                <><span className="material-symbols-rounded" style={{ fontSize: 16 }}>hourglass_empty</span>Wird gespeichert…</>
              ) : (
                <><span className="material-symbols-rounded" style={{ fontSize: 16 }}>check</span>Passwort setzen</>
              )}
            </button>

            <div style={{ textAlign: 'center', marginTop: 4 }}>
              <a href="/login" style={{ fontSize: 13, color: 'var(--frya-primary)', textDecoration: 'none' }}
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
