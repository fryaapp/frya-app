import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, Button, Card, Input } from '../components/m3'
import { useAuthStore } from '../stores/authStore'
import { api } from '../lib/api'

function decodeRole(token: string | null): string {
  if (!token) return 'Unbekannt'
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    const role: string = payload.role ?? 'admin'
    if (role === 'admin') return 'Administrator'
    if (role === 'operator') return 'Bediener'
    if (role === 'customer') return 'Kunde'
    return role
  } catch {
    return 'Administrator'
  }
}

function decodeUsername(token: string | null): string {
  if (!token) return 'Benutzer'
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    return payload.sub ?? payload.email ?? 'Administrator'
  } catch {
    return 'Administrator'
  }
}

export function ProfilePage() {
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)
  const logout = useAuthStore((s) => s.logout)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const role = decodeRole(token)
  const username = decodeUsername(token)

  const handleChangePassword = async () => {
    setError(null)
    if (!newPw.trim()) {
      setError('Bitte neues Passwort eingeben.')
      return
    }
    if (newPw !== confirmPw) {
      setError('Passwörter stimmen nicht überein.')
      return
    }
    setSaving(true)
    try {
      await api.post('/auth/change-password', {
        current_password: currentPw,
        new_password: newPw,
      })
      setToast('Passwort geändert')
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch {
      setError('Passwort konnte nicht geändert werden.')
    } finally {
      setSaving(false)
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 bg-surface-container">
        <Icon name="person" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Profil</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* User Info */}
        <Card variant="outlined">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-full bg-primary-container flex items-center justify-center">
              <Icon name="person" size={28} className="text-on-primary-container" />
            </div>
            <div>
              <p className="text-base font-semibold text-on-surface">{username}</p>
              <p className="text-sm text-on-surface-variant">Rolle: {role}</p>
            </div>
          </div>
        </Card>

        {/* Change Password */}
        <Card variant="outlined">
          <p className="text-sm font-semibold text-on-surface mb-3">Passwort ändern</p>
          <div className="space-y-3">
            <Input
              label="Aktuelles Passwort"
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              autoComplete="current-password"
            />
            <Input
              label="Neues Passwort"
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoComplete="new-password"
            />
            <Input
              label="Passwort bestätigen"
              type="password"
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              autoComplete="new-password"
            />
            {error && <p className="text-error text-xs">{error}</p>}
            <Button
              variant="filled"
              icon="lock"
              onClick={handleChangePassword}
              disabled={saving}
              className="w-full"
            >
              {saving ? 'Wird gespeichert...' : 'Ändern'}
            </Button>
          </div>
        </Card>

        {/* Legal link */}
        <button
          type="button"
          onClick={() => navigate('/legal')}
          className="w-full flex items-center gap-3 px-4 py-3 rounded-m3-sm bg-surface-container-high text-on-surface hover:opacity-80 transition-opacity"
        >
          <Icon name="gavel" size={20} className="text-on-surface-variant" />
          <span className="text-sm font-medium flex-1 text-left">Rechtliches & Datenschutz</span>
          <Icon name="chevron_right" size={20} className="text-on-surface-variant" />
        </button>

        {/* Logout */}
        <div className="pt-4 pb-8">
          <Button variant="outlined" icon="logout" onClick={handleLogout} className="w-full">
            Abmelden
          </Button>
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className="fixed bottom-20 left-1/2 -translate-x-1/2 z-50 px-5 py-2.5 bg-surface-container-highest text-on-surface text-sm rounded-m3 shadow-lg flex items-center gap-2 animate-fade-in"
          onAnimationEnd={() => setTimeout(() => setToast(null), 1500)}
        >
          <Icon name="check_circle" size={18} className="text-success" />
          {toast}
        </div>
      )}
    </div>
  )
}
