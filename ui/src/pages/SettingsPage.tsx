import { useEffect, useState, useCallback } from 'react'
import { Icon, Button, Card } from '../components/m3'
import { useTheme } from '../hooks/useTheme'
import { useAuthStore } from '../stores/authStore'
import { api } from '../lib/api'

type Theme = 'light' | 'dark' | 'system'
type Formality = 'du' | 'sie'
type NotifChannel = 'telegram' | 'email' | null

interface Settings {
  formal_address: boolean
  formality_level: Formality
  emoji_enabled: boolean
  notification_channel: NotifChannel
  theme: Theme
}

const defaultSettings: Settings = {
  formal_address: false,
  formality_level: 'du',
  emoji_enabled: true,
  notification_channel: null,
  theme: 'system',
}

function ChoiceChip({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-4 py-2 rounded-m3-xl text-sm font-semibold transition-all min-h-[40px] ${
        active
          ? 'bg-primary text-on-primary'
          : 'bg-surface-container-high text-on-surface-variant hover:opacity-80'
      }`}
    >
      {label}
    </button>
  )
}

function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 2000)
    return () => clearTimeout(t)
  }, [onDone])

  return (
    <div className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 px-5 py-2.5 bg-surface-container-highest text-on-surface text-sm rounded-m3 shadow-lg flex items-center gap-2 animate-fade-in">
      <Icon name="check_circle" size={18} className="text-success" />
      {message}
    </div>
  )
}

export function SettingsPage() {
  const { theme, setTheme } = useTheme()
  const logout = useAuthStore((s) => s.logout)
  const [settings, setSettings] = useState<Settings>(defaultSettings)
  const [toast, setToast] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.get<Settings>('/settings').then((data) => {
      if (!cancelled) {
        setSettings(data)
        setTheme(data.theme)
      }
    }).catch(() => { /* use defaults */ })
    return () => { cancelled = true }
  }, [setTheme])

  const persist = useCallback((patch: Partial<Settings>) => {
    const next = { ...settings, ...patch }
    setSettings(next)
    setToast(true)
    api.put('/settings', next).catch(() => { /* revert silently */ })
  }, [settings])

  const handleTheme = (t: Theme) => {
    setTheme(t)
    persist({ theme: t })
  }

  const handleFormality = (f: Formality) => {
    persist({ formality_level: f, formal_address: f === 'sie' })
  }

  const handleEmoji = (on: boolean) => {
    persist({ emoji_enabled: on })
  }

  const handleNotif = (ch: NotifChannel) => {
    persist({ notification_channel: ch })
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 bg-surface-container">
        <Icon name="settings" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Einstellungen</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Theme */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-3">Erscheinungsbild</p>
          <div className="flex gap-2 flex-wrap">
            <ChoiceChip label="Hell" active={theme === 'light'} onClick={() => handleTheme('light')} />
            <ChoiceChip label="Dunkel" active={theme === 'dark'} onClick={() => handleTheme('dark')} />
            <ChoiceChip label="System" active={theme === 'system'} onClick={() => handleTheme('system')} />
          </div>
        </Card>

        {/* Formality */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-3">Anrede</p>
          <div className="flex gap-2">
            <ChoiceChip label="Du" active={settings.formality_level === 'du'} onClick={() => handleFormality('du')} />
            <ChoiceChip label="Sie" active={settings.formality_level === 'sie'} onClick={() => handleFormality('sie')} />
          </div>
        </Card>

        {/* Emoji */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-3">Emojis in Fryas Antworten</p>
          <div className="flex gap-2">
            <ChoiceChip label="Ein" active={settings.emoji_enabled} onClick={() => handleEmoji(true)} />
            <ChoiceChip label="Aus" active={!settings.emoji_enabled} onClick={() => handleEmoji(false)} />
          </div>
        </Card>

        {/* Notifications */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-3">Benachrichtigungen</p>
          <div className="flex gap-2 flex-wrap">
            <ChoiceChip label="Telegram" active={settings.notification_channel === 'telegram'} onClick={() => handleNotif('telegram')} />
            <ChoiceChip label="E-Mail" active={settings.notification_channel === 'email'} onClick={() => handleNotif('email')} />
            <ChoiceChip label="Aus" active={settings.notification_channel === null} onClick={() => handleNotif(null)} />
          </div>
        </Card>

        {/* Logout */}
        <div className="pt-4 pb-8">
          <Button variant="outlined" icon="logout" onClick={logout} className="w-full">
            Abmelden
          </Button>
        </div>
      </div>

      {toast && <Toast message="Gespeichert" onDone={() => setToast(false)} />}
    </div>
  )
}
