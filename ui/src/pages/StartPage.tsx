import { useEffect, useState } from 'react'
import { Icon } from '../components/m3'
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
      <div className="flex-1 flex flex-col items-center justify-center px-4">
        <div className="w-full max-w-[520px] px-5 md:px-7 text-center">
          {/* Avatar */}
          <div className="flex justify-center mb-4">
            <div className="w-14 h-14 rounded-[20px] bg-primary-container flex items-center justify-center">
              <Icon name="eco" size={28} filled className="text-on-primary-container" />
            </div>
          </div>

          {/* Greeting */}
          {loading ? (
            <div className="animate-pulse space-y-3 mb-6">
              <div className="h-7 w-48 bg-surface-container-high rounded-lg mx-auto" />
              <div className="h-4 w-64 bg-surface-container-high rounded mx-auto" />
            </div>
          ) : data && (
            <>
              <h1 className="font-display font-semibold text-on-surface leading-tight mb-2" style={{ fontSize: 'clamp(24px, 4vw, 30px)', letterSpacing: '-0.01em' }}>
                {data.greeting}
              </h1>
              <p className="text-sm text-on-surface-variant leading-[1.7] max-w-[420px] mx-auto">
                {data.status_summary}
              </p>
            </>
          )}

          {/* Urgent warning */}
          {data?.urgent && (
            <div className="mt-4 bg-error-container rounded-[14px] px-4 py-3 text-left flex items-start gap-2.5 max-w-[440px] mx-auto">
              <Icon name="priority_high" size={18} className="text-error shrink-0 mt-0.5" />
              <p className="text-[13px] text-error leading-snug">{data.urgent.text}</p>
            </div>
          )}

          {/* Suggestion chips */}
          {data?.suggestions && data.suggestions.length > 0 && (
            <div className="flex flex-wrap justify-center gap-1.5 mt-5 max-w-[440px] mx-auto">
              {data.suggestions.map((label) => (
                <button
                  key={label}
                  onClick={() => handleSend(label)}
                  className="inline-flex items-center gap-1 px-3.5 py-1.5 rounded-[20px] border border-outline-variant text-on-surface text-xs font-medium hover:bg-surface-container-high hover:border-outline transition-all cursor-pointer"
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Chat input — in greeting area, not fixed */}
          <div className="mt-5 max-w-[440px] mx-auto">
            <ChatInput onSend={handleSend} placeholder="Nachricht an Frya…" />
          </div>
        </div>
      </div>
    </div>
  )
}
