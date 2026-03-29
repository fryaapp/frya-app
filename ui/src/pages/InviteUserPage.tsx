import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

type Role = 'operator' | 'admin'

export function InviteUserPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('operator')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState<{ username: string; email: string; invite_sent: boolean } | null>(null)
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const result = await api.post<{ username: string; email: string; role: string; invite_sent: boolean }>(
        '/auth/users',
        { username, email, role }
      )
      setSuccess({ username: result.username, email: result.email, invite_sent: result.invite_sent })
    } catch (err: unknown) {
      const e = err as { status?: number; message?: string }
      if (e?.status === 409) setError('Benutzername ist bereits vergeben.')
      else if (e?.status === 403) setError('Keine Berechtigung. Nur Admins können Nutzer anlegen.')
      else setError('Fehler beim Anlegen des Nutzers. Bitte erneut versuchen.')
    } finally {
      setLoading(false)
    }
  }

  const reset = () => {
    setSuccess(null)
    setUsername('')
    setEmail('')
    setRole('operator')
    setError('')
  }

  return (
    <div
      className="flex items-center justify-center min-h-screen p-4"
      style={{ background: 'var(--frya-page-bg)' }}
    >
      {/* warm glow */}
      <div
        aria-hidden
        style={{
          position: 'fixed',
          top: 0,
          left: '50%',
          transform: 'translateX(-50%)',
          width: '600px',
          height: '400px',
          background: 'radial-gradient(ellipse at 50% 0%, rgba(144,75,34,0.18) 0%, transparent 70%)',
          pointerEvents: 'none',
        }}
      />

      <div
        className="w-full max-w-sm animate-fade-up"
        style={{
          background: 'var(--frya-surface-container-low)',
          borderRadius: 28,
          padding: '40px 32px 36px',
          boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
        }}
      >
        {/* Back */}
        <button
          type="button"
          onClick={() => navigate(-1)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--frya-on-surface-variant)',
            fontSize: 13,
            padding: 0,
            marginBottom: 24,
          }}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18 }}>arrow_back</span>
          Zurück
        </button>

        {success ? (
          /* ── Success State ── */
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                width: 56,
                height: 56,
                borderRadius: 20,
                background: 'var(--frya-success-container)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 16px',
              }}
            >
              <span
                className="material-symbols-rounded"
                style={{ fontSize: 28, color: 'var(--frya-success)', fontVariationSettings: "'FILL' 1" }}
              >
                check_circle
              </span>
            </div>
            <h2
              style={{
                fontFamily: 'Outfit, sans-serif',
                fontSize: 22,
                fontWeight: 700,
                color: 'var(--frya-on-surface)',
                marginBottom: 8,
              }}
            >
              Konto angelegt
            </h2>
            <p style={{ color: 'var(--frya-on-surface-variant)', fontSize: 14, lineHeight: 1.6, marginBottom: 20 }}>
              <strong style={{ color: 'var(--frya-on-surface)' }}>{success.username}</strong> wurde erfolgreich erstellt.
            </p>

            {success.invite_sent ? (
              <div
                style={{
                  background: 'var(--frya-surface-container-high)',
                  borderRadius: 16,
                  padding: '12px 16px',
                  fontSize: 13,
                  color: 'var(--frya-on-surface-variant)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  marginBottom: 24,
                  textAlign: 'left',
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 18, color: 'var(--frya-info)', flexShrink: 0 }}>
                  mail
                </span>
                Einladungs-E-Mail wurde an <strong style={{ color: 'var(--frya-on-surface)' }}>{success.email}</strong> gesendet.
              </div>
            ) : (
              <div
                style={{
                  background: 'var(--frya-warning-container)',
                  borderRadius: 16,
                  padding: '12px 16px',
                  fontSize: 13,
                  color: 'var(--frya-warning)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  marginBottom: 24,
                  textAlign: 'left',
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 18, flexShrink: 0 }}>warning</span>
                E-Mail konnte nicht gesendet werden. Bitte Passwort-Reset manuell veranlassen.
              </div>
            )}

            <div style={{ display: 'flex', gap: 10 }}>
              <button
                type="button"
                onClick={reset}
                style={{
                  flex: 1,
                  padding: '13px 16px',
                  background: 'var(--frya-primary)',
                  color: 'var(--frya-on-primary)',
                  border: 'none',
                  borderRadius: 28,
                  fontFamily: 'inherit',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>person_add</span>
                Weiteren anlegen
              </button>
              <button
                type="button"
                onClick={() => navigate('/settings')}
                style={{
                  flex: 1,
                  padding: '13px 16px',
                  background: 'var(--frya-surface-container-high)',
                  color: 'var(--frya-on-surface)',
                  border: 'none',
                  borderRadius: 28,
                  fontFamily: 'inherit',
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Fertig
              </button>
            </div>
          </div>
        ) : (
          /* ── Form ── */
          <>
            <div style={{ textAlign: 'center', marginBottom: 28 }}>
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 20,
                  background: 'var(--frya-primary-container)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  margin: '0 auto 16px',
                }}
              >
                <span
                  className="material-symbols-rounded"
                  style={{ fontSize: 28, color: 'var(--frya-on-primary-container)', fontVariationSettings: "'FILL' 1" }}
                >
                  person_add
                </span>
              </div>
              <h1
                style={{
                  fontFamily: 'Outfit, sans-serif',
                  fontSize: 26,
                  fontWeight: 700,
                  letterSpacing: '-0.02em',
                  color: 'var(--frya-on-surface)',
                  lineHeight: 1.2,
                  marginBottom: 6,
                }}
              >
                Konto anlegen
              </h1>
              <p style={{ color: 'var(--frya-on-surface-variant)', fontSize: 13 }}>
                Einladungs-E-Mail wird automatisch versendet
              </p>
            </div>

            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Username */}
              <div style={{ position: 'relative' }}>
                <span
                  className="material-symbols-rounded"
                  style={{
                    position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)',
                    fontSize: 18, color: 'var(--frya-on-surface-variant)', pointerEvents: 'none',
                  }}
                >
                  badge
                </span>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s/g, ''))}
                  placeholder="Benutzername"
                  required
                  autoFocus
                  autoComplete="off"
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
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="E-Mail-Adresse"
                  required
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

              {/* Rolle */}
              <div
                style={{
                  background: 'var(--frya-surface-container-high)',
                  borderRadius: 28,
                  padding: '8px',
                  display: 'flex',
                  gap: 4,
                }}
              >
                {(['operator', 'admin'] as Role[]).map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => setRole(r)}
                    style={{
                      flex: 1,
                      padding: '10px 12px',
                      borderRadius: 20,
                      border: 'none',
                      fontFamily: 'inherit',
                      fontSize: 13,
                      fontWeight: 600,
                      cursor: 'pointer',
                      transition: 'all 0.2s',
                      background: role === r ? 'var(--frya-primary-container)' : 'transparent',
                      color: role === r ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface-variant)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 6,
                    }}
                  >
                    <span className="material-symbols-rounded" style={{ fontSize: 15 }}>
                      {r === 'operator' ? 'person' : 'admin_panel_settings'}
                    </span>
                    {r === 'operator' ? 'Nutzer' : 'Admin'}
                  </button>
                ))}
              </div>

              {error && (
                <div
                  style={{
                    background: 'var(--frya-error-container)',
                    borderRadius: 12,
                    padding: '10px 16px',
                    fontSize: 13,
                    color: 'var(--frya-error)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
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
                  marginTop: 8,
                  width: '100%',
                  padding: '15px 20px',
                  background: loading ? 'var(--frya-primary-container)' : 'var(--frya-primary)',
                  color: loading ? 'var(--frya-on-primary-container)' : 'var(--frya-on-primary)',
                  border: 'none', borderRadius: 28,
                  fontFamily: 'inherit', fontSize: 14, fontWeight: 600,
                  cursor: loading ? 'not-allowed' : 'pointer',
                  transition: 'all 0.2s',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                {loading ? (
                  <>
                    <span className="material-symbols-rounded" style={{ fontSize: 16 }}>hourglass_empty</span>
                    Wird angelegt…
                  </>
                ) : (
                  <>
                    <span className="material-symbols-rounded" style={{ fontSize: 16 }}>send</span>
                    Einladen
                  </>
                )}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
