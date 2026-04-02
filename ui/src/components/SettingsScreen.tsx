import { useState } from 'react'
import { useFryaStore } from '../stores/fryaStore'
import { useTheme } from '../hooks/useTheme'
import { LegalModal } from './LegalModal'

type LegalTab = 'datenschutz' | 'impressum' | 'agb'

export function SettingsScreen() {
  const [legalTab, setLegalTab] = useState<LegalTab | null>(null)
  const { theme, setTheme } = useTheme()
  const goHome = useFryaStore((s) => s.goHome)
  const logout = useFryaStore((s) => s.logout)
  const messageCount = useFryaStore((s) => s.messages.length)
  const startChat = useFryaStore((s) => s.startChat)

  const handleLogout = () => {
    // Clear old authStore too
    localStorage.removeItem('frya-token')
    localStorage.removeItem('frya-refresh')
    localStorage.removeItem('frya-expires-at')
    logout()
    window.location.href = '/login'
  }

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--frya-surface)',
      }}
    >
      {/* Top bar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '8px 16px',
          background: 'var(--frya-surface)',
          flexShrink: 0,
        }}
      >
        <button
          onClick={goHome}
          style={{
            width: 28, height: 28, borderRadius: 8,
            border: 'none', background: 'transparent',
            color: 'var(--frya-on-surface-variant)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
          }}
          aria-label="Zurück"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>arrow_back</span>
        </button>
        <span style={{ fontSize: 14, fontWeight: 600, fontFamily: "'Outfit', sans-serif", color: 'var(--frya-on-surface)' }}>
          Einstellungen
        </span>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '24px 20px', maxWidth: 440, width: '100%', margin: '0 auto' }}>
        {/* Profile section */}
        <div
          style={{
            background: 'var(--frya-surface-container)',
            borderRadius: 16,
            padding: '20px',
            marginBottom: 16,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <div style={{
              width: 40, height: 40, borderRadius: '50%',
              background: 'var(--frya-primary-container)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <span className="material-symbols-rounded" style={{ fontSize: 20, color: 'var(--frya-on-primary-container)' }}>person</span>
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--frya-on-surface)', fontFamily: "'Outfit', sans-serif" }}>
                Mein Konto
              </div>
              <div style={{ fontSize: 11, color: 'var(--frya-on-surface-variant)' }}>
                Alpha-Tester
              </div>
            </div>
          </div>

          {/* Theme Switcher */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--frya-outline-variant)' }}>
            <span className="material-symbols-rounded" style={{ fontSize: 18, color: 'var(--frya-on-surface-variant)' }}>
              {theme === 'dark' ? 'dark_mode' : theme === 'light' ? 'light_mode' : 'brightness_auto'}
            </span>
            <span style={{ flex: 1, fontSize: 13, color: 'var(--frya-on-surface)', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>Theme</span>
            <div style={{ display: 'flex', gap: 2, background: 'var(--frya-surface)', borderRadius: 10, padding: 2 }}>
              {([['dark', 'dark_mode', 'Dunkel'], ['light', 'light_mode', 'Hell'], ['system', 'brightness_auto', 'Auto']] as const).map(([val, icon, label]) => (
                <button
                  key={val}
                  onClick={() => setTheme(val)}
                  style={{
                    padding: '4px 10px', borderRadius: 8, border: 'none',
                    background: theme === val ? 'var(--frya-primary-container)' : 'transparent',
                    color: theme === val ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface-variant)',
                    fontSize: 11, fontWeight: theme === val ? 600 : 400,
                    fontFamily: "'Plus Jakarta Sans', sans-serif",
                    cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4,
                    transition: 'all 0.15s',
                  }}
                >
                  <span className="material-symbols-rounded" style={{ fontSize: 14 }}>{icon}</span>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <SettingsItem icon="translate" label="Sprache" hint="Deutsch" />
          <SettingsItem icon="notifications" label="Benachrichtigungen" hint="An" />
        </div>

        {/* Chat section */}
        {messageCount > 0 && (
          <div
            style={{
              background: 'var(--frya-surface-container)',
              borderRadius: 16,
              padding: '16px 20px',
              marginBottom: 16,
            }}
          >
            <button
              onClick={() => startChat()}
              style={{
                width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 0', border: 'none', background: 'transparent',
                color: 'var(--frya-on-surface)', cursor: 'pointer',
                fontFamily: "'Plus Jakarta Sans', sans-serif", fontSize: 13,
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 18, color: 'var(--frya-primary)' }}>chat</span>
              <span style={{ flex: 1, textAlign: 'left' }}>Zum Chat ({messageCount} Nachrichten)</span>
              <span className="material-symbols-rounded" style={{ fontSize: 16, color: 'var(--frya-on-surface-variant)' }}>chevron_right</span>
            </button>
          </div>
        )}

        {/* Info section */}
        <div
          style={{
            background: 'var(--frya-surface-container)',
            borderRadius: 16,
            padding: '16px 20px',
            marginBottom: 16,
          }}
        >
          <SettingsItem icon="info" label="Version" hint="Alpha 0.9" />
          <SettingsItem icon="shield" label="Datenschutz" hint="" onClick={() => setLegalTab('datenschutz')} />
          <SettingsItem icon="description" label="Impressum" hint="" onClick={() => setLegalTab('impressum')} />
          <SettingsItem icon="gavel" label="AGB" hint="" onClick={() => setLegalTab('agb')} />
        </div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            padding: '14px',
            borderRadius: 16,
            border: '1px solid var(--frya-outline-variant)',
            background: 'transparent',
            color: 'var(--frya-on-surface)',
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            cursor: 'pointer',
          }}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18 }}>logout</span>
          Abmelden
        </button>
      </div>

      <LegalModal
        open={legalTab !== null}
        initialTab={legalTab || 'datenschutz'}
        onClose={() => setLegalTab(null)}
      />
    </div>
  )
}

function SettingsItem({ icon, label, hint, onClick }: { icon: string; label: string; hint: string; onClick?: () => void }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 0',
        borderBottom: '1px solid var(--frya-outline-variant)',
        width: '100%',
        background: 'transparent',
        border: 'none',
        borderBlockEnd: '1px solid var(--frya-outline-variant)',
        cursor: onClick ? 'pointer' : 'default',
        textAlign: 'left',
      }}
    >
      <span className="material-symbols-rounded" style={{ fontSize: 18, color: 'var(--frya-on-surface-variant)' }}>{icon}</span>
      <span style={{ flex: 1, fontSize: 13, color: 'var(--frya-on-surface)', fontFamily: "'Plus Jakarta Sans', sans-serif" }}>{label}</span>
      {hint && <span style={{ fontSize: 12, color: 'var(--frya-on-surface-variant)' }}>{hint}</span>}
      {onClick && <span className="material-symbols-rounded" style={{ fontSize: 14, color: 'var(--frya-on-surface-variant)' }}>chevron_right</span>}
    </Tag>
  )
}
