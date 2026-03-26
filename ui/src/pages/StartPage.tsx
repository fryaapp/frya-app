import { useEffect, useState } from 'react'
import { Icon, Chip } from '../components/m3'
import { ChatInput } from '../components/chat'
import { useUiStore, type ContextType } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import { api } from '../lib/api'

interface StatusData {
  inboxCount: number
  deadlineSummary: string | null
  urgentWarning: string | null
}

const shortcuts: { label: string; icon: string; context: ContextType }[] = [
  { label: 'Inbox', icon: 'inbox', context: 'inbox' },
  { label: 'Fristen', icon: 'event', context: 'deadlines' },
  { label: 'Belege einwerfen', icon: 'upload_file', context: 'upload_status' },
  { label: 'Vorgänge', icon: 'folder_open', context: 'cases' },
]

/**
 * StartPage — Ruhezustand (Idle).
 * Frya-Avatar + Begrüßung vertikal+horizontal zentriert.
 * Status-Info, Shortcut-Chips, Eingabefeld unten.
 * KEIN Split, kein Chat-Bereich.
 */
export function StartPage() {
  const openSplit = useUiStore((s) => s.openSplit)
  const [status, setStatus] = useState<StatusData>({ inboxCount: 0, deadlineSummary: null, urgentWarning: null })
  const [userName, setUserName] = useState('')

  // Fetch status data on mount
  useEffect(() => {
    let cancelled = false

    async function loadStatus() {
      try {
        // Try greeting endpoint first (P1, may not exist yet)
        const greeting = await api.get<{
          greeting: string
          status_summary: string
          urgent: string | null
          suggestions: string[]
        }>('/greeting')
        if (!cancelled) {
          setUserName(greeting.greeting)
          setStatus({
            inboxCount: 0,
            deadlineSummary: greeting.status_summary,
            urgentWarning: greeting.urgent,
          })
        }
      } catch (e) {
        if (cancelled) return
        // Fallback: build status from inbox + deadlines
        try {
          const [inbox, deadlines] = await Promise.all([
            api.get<{ count: number }>('/inbox').catch(() => ({ count: 0 })),
            api.get<{ summary: string; overdue: unknown[] }>('/deadlines').catch(() => ({ summary: '', overdue: [] })),
          ])
          if (!cancelled) {
            const parts: string[] = []
            if (inbox.count > 0) parts.push(`${inbox.count} Beleg${inbox.count > 1 ? 'e' : ''} warten auf dich`)
            if (deadlines.summary) parts.push(deadlines.summary)

            setStatus({
              inboxCount: inbox.count,
              deadlineSummary: parts.join(' · ') || null,
              urgentWarning: (deadlines.overdue as unknown[])?.length > 0
                ? `${(deadlines.overdue as unknown[]).length} überfällige Frist${(deadlines.overdue as unknown[]).length > 1 ? 'en' : ''}!`
                : null,
            })
          }
        } catch {
          // API not available — show static greeting
        }
      }
    }

    loadStatus()
    return () => { cancelled = true }
  }, [])

  // Get greeting time-based
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Guten Morgen' : hour < 18 ? 'Hallo' : 'Guten Abend'
  const displayName = userName || greeting

  const handleSend = (text: string) => {
    useChatStore.getState().addUserMessage(text)
    openSplit('none')
  }

  const handleChipClick = (ctx: ContextType) => {
    openSplit(ctx)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Center content */}
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        {/* Frya Avatar */}
        <div className="w-20 h-20 rounded-full bg-primary-container flex items-center justify-center mb-5 shadow-lg">
          <span className="text-3xl font-display font-bold text-on-primary-container">F</span>
        </div>

        {/* Greeting */}
        <h1 className="text-2xl font-display font-bold text-on-surface mb-1">
          {displayName}!
        </h1>
        <p className="text-sm text-on-surface-variant mb-4">Was kann ich für dich tun?</p>

        {/* Status info */}
        {status.deadlineSummary && (
          <p className="text-xs text-on-surface-variant/70 mb-2 text-center">
            {status.deadlineSummary}
          </p>
        )}

        {/* Urgent warning */}
        {status.urgentWarning && (
          <div className="flex items-center gap-2 px-4 py-2 bg-error-container rounded-m3 mb-4">
            <Icon name="warning" size={18} className="text-error" />
            <span className="text-sm text-error font-medium">{status.urgentWarning}</span>
          </div>
        )}

        {/* Shortcut chips */}
        <div className="flex flex-wrap justify-center gap-2 mt-2">
          {shortcuts.map((s) => (
            <Chip
              key={s.context}
              label={s.label}
              icon={s.icon}
              color="primary"
              onClick={() => handleChipClick(s.context)}
            />
          ))}
        </div>
      </div>

      {/* Input at bottom */}
      <ChatInput
        onSend={handleSend}
        placeholder="Nachricht an Frya\u2026"
      />
    </div>
  )
}
