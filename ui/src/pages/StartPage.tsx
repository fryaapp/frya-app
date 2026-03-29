import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatInput } from '../components/chat'
import { FryaAvatar } from '../components/chat/FryaAvatar'
import { Icon } from '../components/m3'
import { useUiStore } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import { api } from '../lib/api'

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

/**
 * StartPage — Clean, minimal greeting.
 * Avatar + greeting + one conversational prompt + input.
 * No data dump. The user should feel invited to start, not overwhelmed.
 */
export function StartPage() {
  const openSplit = useUiStore((s) => s.openSplit)
  const navigate = useNavigate()
  const [data, setData] = useState<GreetingResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await api.get<GreetingResponse>('/greeting')
        if (!cancelled) setData(res)
      } catch {
        if (!cancelled) {
          setData({
            greeting: 'Hallo!',
            status_summary: '',
            urgent: null,
            suggestions: ['Inbox öffnen', 'Belege hochladen'],
          })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  const handleSend = (text: string) => {
    const store = useChatStore.getState()
    store.addUserMessage(text)
    store.setPendingSend(text)
    openSplit('none')
  }

  // Build a short, conversational prompt from the API data
  const prompt = buildPrompt(data)

  const quickActions = [
    { icon: 'inbox', label: 'Inbox', desc: 'Offene Belege', path: '/inbox', context: 'inbox' as const },
    { icon: 'upload', label: 'Upload', desc: 'Belege hochladen', path: '/upload', context: 'upload_status' as const },
    { icon: 'schedule', label: 'Fristen', desc: 'Nächste Termine', path: '/deadlines', context: 'deadlines' as const },
    { icon: 'bar_chart', label: 'Finanzen', desc: 'Übersicht', path: '/finance', context: 'finance' as const },
  ]

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      <div className="flex-1 flex flex-col items-center pt-8 px-4 pb-4">
        <div className="w-full max-w-[440px] text-center">

          {/* FRYA Avatar */}
          <div className="flex justify-center mb-4">
            <FryaAvatar size={72} />
          </div>

          {/* Greeting */}
          {loading ? (
            <div className="animate-pulse space-y-3 mb-6">
              <div className="h-7 w-48 bg-surface-container-high rounded-lg mx-auto" />
              <div className="h-4 w-64 bg-surface-container-high rounded mx-auto opacity-60" />
            </div>
          ) : (
            <div className="mb-5 animate-fade-up">
              <h1
                className="font-display font-bold text-on-surface mb-2"
                style={{ fontSize: 'clamp(22px, 4.5vw, 30px)', letterSpacing: '-0.02em', lineHeight: 1.15 }}
              >
                {data?.greeting || 'Hallo!'}
              </h1>

              {prompt && (
                <p className="text-sm text-on-surface-variant leading-relaxed max-w-[340px] mx-auto">
                  {prompt}
                </p>
              )}
            </div>
          )}

          {/* Quick-Action Grid */}
          <div className="grid grid-cols-4 gap-2 mb-5 animate-fade-up stagger-1">
            {quickActions.map((qa) => (
              <button
                key={qa.path}
                onClick={() => { openSplit(qa.context); navigate(qa.path) }}
                className="flex flex-col items-center gap-1.5 p-3 rounded-2xl transition-all cursor-pointer"
                style={{
                  background: 'var(--frya-surface-container)',
                  border: '1px solid transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--frya-surface-container-high)'
                  e.currentTarget.style.borderColor = 'var(--frya-primary)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'var(--frya-surface-container)'
                  e.currentTarget.style.borderColor = 'transparent'
                }}
              >
                <Icon name={qa.icon} size={22} className="text-primary" />
                <span className="text-[10px] font-medium text-on-surface leading-tight">{qa.label}</span>
              </button>
            ))}
          </div>

          {/* Suggestion chips */}
          {data?.suggestions && data.suggestions.length > 0 && (
            <div className="flex flex-wrap justify-center gap-2 mb-4 animate-fade-up stagger-2">
              {data.suggestions.slice(0, 3).map((label) => (
                <button
                  key={label}
                  onClick={() => handleSend(label)}
                  className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[11px] font-medium transition-all cursor-pointer"
                  style={{
                    borderRadius: '18px',
                    border: '1px solid var(--frya-outline-variant)',
                    color: 'var(--frya-on-surface)',
                    background: 'transparent',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--frya-surface-container-high)'
                    e.currentTarget.style.borderColor = 'var(--frya-primary)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.borderColor = 'var(--frya-outline-variant)'
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Chat input */}
          <div className="animate-fade-up stagger-3">
            <ChatInput onSend={handleSend} placeholder="Lass uns beginnen..." />
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Turn the API summary into one friendly, conversational sentence.
 * Instead of "3 Belege, 1 überfällig, 2 Fristen" →
 * "Sollen wir mit den offenen Freigaben starten?"
 */
function buildPrompt(data: GreetingResponse | null): string | null {
  if (!data) return null

  // If something is urgent, mention it gently
  if (data.urgent && data.urgent.priority === 'HIGH') {
    return data.urgent.text
  }

  // Convert the summary into a conversational prompt
  const summary = data.status_summary
  if (!summary) return null

  // Check for open items in the summary
  const hasInbox = /beleg|freigabe/i.test(summary)
  const hasOverdue = /überfällig/i.test(summary)
  const hasDeadlines = /frist/i.test(summary)

  if (hasOverdue) return 'Es gibt überfällige Posten — sollen wir uns die anschauen?'
  if (hasInbox) return 'Es warten Belege auf dich. Sollen wir starten?'
  if (hasDeadlines) return 'Es stehen Fristen an. Soll ich dir mehr zeigen?'

  // Fallback: if summary is short enough, show it directly
  if (summary.length < 60) return summary

  return 'Was kann ich für dich tun?'
}
