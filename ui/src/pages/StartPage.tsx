import { useEffect, useState } from 'react'
import { Icon, Card, Chip } from '../components/m3'
import { ChatInput } from '../components/chat'
import { useUiStore } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import { api } from '../lib/api'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface GreetingResponse {
  greeting: string
  status_summary: string
  urgent: {
    text: string
    case_ref: string | null
    priority: string
  } | null
  suggestions: string[]
}

/* ------------------------------------------------------------------ */
/*  StartPage                                                          */
/* ------------------------------------------------------------------ */

/**
 * StartPage — Idle greeting screen.
 * Eco avatar, API greeting, status summary, urgent warning, suggestion chips, chat input.
 */
export function StartPage() {
  const openSplit = useUiStore((s) => s.openSplit)

  const [data, setData] = useState<GreetingResponse | null>(null)
  const [loading, setLoading] = useState(true)

  // ---- Fetch greeting from API ----
  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await api.get<GreetingResponse>('/greeting')
        if (!cancelled) {
          setData(res)
        }
      } catch {
        // Fallback if API unavailable
        if (!cancelled) {
          setData({
            greeting: 'Hallo!',
            status_summary: 'Was kann ich für dich tun?',
            urgent: null,
            suggestions: ['Inbox öffnen', 'Vorgänge anzeigen'],
          })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  // ---- Handlers ----
  const handleSend = (text: string) => {
    useChatStore.getState().addUserMessage(text)
    openSplit('none')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Vertically centered content area */}
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-[440px] text-center">
          {/* ---- Eco icon avatar ---- */}
          <div className="flex justify-center mb-4">
            <div className="w-12 h-12 rounded-2xl bg-primary-container flex items-center justify-center">
              <Icon name="eco" size={24} filled className="text-on-primary-container" />
            </div>
          </div>

          {/* ---- Greeting from API ---- */}
          {loading ? (
            <div className="animate-pulse space-y-2 mb-6">
              <div className="h-6 w-40 bg-surface-container-high rounded mx-auto" />
              <div className="h-4 w-56 bg-surface-container-high rounded mx-auto" />
            </div>
          ) : data && (
            <>
              <h1 className="text-lg font-display font-bold text-on-surface leading-tight mb-1">
                {data.greeting}
              </h1>
              <p className="text-sm text-on-surface-variant mb-6">
                {data.status_summary}
              </p>
            </>
          )}

          {/* ---- Urgent warning card ---- */}
          {data?.urgent && (
            <Card variant="outlined" className="mb-5 text-left bg-warning-container border-warning">
              <div className="flex items-start gap-3">
                <Icon name="warning" size={20} className="text-warning shrink-0 mt-0.5" />
                <p className="text-sm text-on-surface">{data.urgent.text}</p>
              </div>
            </Card>
          )}

          {/* ---- Suggestion chips from API ---- */}
          {data?.suggestions && data.suggestions.length > 0 && (
            <div className="flex flex-wrap justify-center gap-2 mb-4">
              {data.suggestions.map((label) => (
                <Chip
                  key={label}
                  label={label}
                  color="primary"
                  onClick={() => handleSend(label)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---- Chat input at bottom ---- */}
      <ChatInput
        onSend={handleSend}
        placeholder="Nachricht an Frya\u2026"
      />
    </div>
  )
}
