import { useEffect, useState, useCallback } from 'react'
import { BugReportOverlay } from './layout/BugReportOverlay'
import { FryaAvatar } from './chat/FryaAvatar'
import { ChatInputBar } from './chat/ChatInputBar'
import { useFryaStore } from '../stores/fryaStore'
import { api } from '../lib/api'
// LegalModal is available in SettingsScreen

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

const chips = [
  { icon: 'inbox', label: 'Inbox' },
  { icon: 'account_balance', label: 'Finanzen' },
  { icon: 'description', label: 'Belege' },
  { icon: 'download', label: 'Export' },
]

export function GreetingScreen() {
  const startChat = useFryaStore((s) => s.startChat)
  const messageCount = useFryaStore((s) => s.messages.length)
  const [data, setData] = useState<GreetingResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [bugOpen, setBugOpen] = useState(false)
  const [bugShot, setBugShot] = useState<string | null>(null)

  const handleBugReport = useCallback(async () => {
    try {
      const el = document.getElementById('root')
      if (el) {
        const { default: html2canvas } = await import('html2canvas')
        const canvas = await html2canvas(el, { backgroundColor: null, scale: 1, logging: false, useCORS: true })
        setBugShot(canvas.toDataURL('image/jpeg', 0.7))
      }
    } catch { setBugShot(null) }
    setBugOpen(true)
  }, [])

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
            suggestions: [],
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
    startChat(text)
  }

  const handleChip = (label: string) => {
    startChat(label)
  }

  const statusText = buildPrompt(data)
  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--frya-surface)',
      }}
    >
      {/* Top bar — BugReport + Settings oben rechts */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', padding: '8px 12px', gap: 4, flexShrink: 0 }}>
        <button
          onClick={handleBugReport}
          style={{
            width: 32, height: 32, borderRadius: 8, border: 'none',
            background: 'transparent', color: 'var(--frya-on-surface-variant)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          }}
          aria-label="Problem melden"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>bug_report</span>
        </button>
        <button
          onClick={() => useFryaStore.getState().openSettings()}
          style={{
            width: 32, height: 32, borderRadius: 8, border: 'none',
            background: 'transparent', color: 'var(--frya-on-surface-variant)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
          }}
          aria-label="Einstellungen"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>settings</span>
        </button>
      </div>

      {/* Center content */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 20px 0',
          overflow: 'auto',
        }}
      >
        <div style={{ maxWidth: 440, width: '100%', textAlign: 'center' }}>
          {/* Avatar */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginBottom: 16,
              animation: 'frya-fade-up 400ms ease both',
            }}
          >
            <FryaAvatar size={80} />
          </div>

          {/* Greeting text */}
          {loading ? (
            <div style={{ marginBottom: 24 }}>
              <div
                style={{
                  height: 28,
                  width: 180,
                  background: 'var(--frya-surface-container-high)',
                  borderRadius: 8,
                  margin: '0 auto 12px',
                  animation: 'frya-pulse 1.5s ease-in-out infinite',
                }}
              />
              <div
                style={{
                  height: 16,
                  width: 240,
                  background: 'var(--frya-surface-container-high)',
                  borderRadius: 6,
                  margin: '0 auto',
                  opacity: 0.6,
                  animation: 'frya-pulse 1.5s ease-in-out infinite 200ms',
                }}
              />
            </div>
          ) : (
            <div
              style={{
                marginBottom: 20,
                animation: 'frya-fade-up 400ms ease 100ms both',
              }}
            >
              <h1
                style={{
                  fontFamily: "'Outfit', sans-serif",
                  fontSize: 26,
                  fontWeight: 600,
                  color: 'var(--frya-on-surface)',
                  letterSpacing: '-0.02em',
                  lineHeight: 1.15,
                  margin: '0 0 8px',
                }}
              >
                {data?.greeting || 'Hallo!'}
              </h1>

              {statusText && (
                <p
                  style={{
                    fontSize: 13,
                    color: 'var(--frya-on-surface-variant)',
                    lineHeight: 1.5,
                    maxWidth: 340,
                    margin: '0 auto',
                    fontFamily: "'Plus Jakarta Sans', sans-serif",
                  }}
                >
                  {statusText}
                </p>
              )}
            </div>
          )}

          {/* Urgent banner */}
          {data?.urgent && data.urgent.priority === 'HIGH' && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                background: 'var(--frya-warning-container)',
                color: 'var(--frya-warning)',
                borderRadius: 12,
                padding: '10px 14px',
                marginBottom: 16,
                fontSize: 13,
                fontFamily: "'Plus Jakarta Sans', sans-serif",
                textAlign: 'left',
                animation: 'frya-fade-up 400ms ease 200ms both',
              }}
            >
              <span
                className="material-symbols-rounded"
                style={{
                  fontSize: 18,
                  flexShrink: 0,
                  fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 18",
                }}
              >
                warning
              </span>
              <span>{data.urgent.text}</span>
            </div>
          )}

          {/* Back to chat button (if chat has messages) */}
          {messageCount > 0 && (
            <div style={{ marginBottom: 12, animation: 'frya-fade-up 400ms ease 200ms both' }}>
              <button
                onClick={() => startChat()}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '10px 20px',
                  fontSize: 13,
                  fontWeight: 600,
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  borderRadius: 20,
                  border: 'none',
                  background: 'var(--frya-primary)',
                  color: 'var(--frya-on-primary)',
                  cursor: 'pointer',
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>chat</span>
                Zurück zum Chat ({messageCount})
              </button>
            </div>
          )}

          {/* Chips row */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              gap: 8,
              flexWrap: 'wrap',
              marginBottom: 20,
              animation: 'frya-fade-up 400ms ease 250ms both',
            }}
          >
            {chips.map((chip) => (
              <ChipButton
                key={chip.label}
                icon={chip.icon}
                label={chip.label}
                onClick={() => handleChip(chip.label)}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Input bar at bottom */}
      <ChatInputBar onSend={handleSend} placeholder="Nachricht an Frya…" />
      <BugReportOverlay open={bugOpen} onClose={() => { setBugOpen(false); setBugShot(null) }} screenshot={bugShot} />


      <style>{`
        @keyframes frya-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}

function ChipButton({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 14px',
        fontSize: 12,
        fontWeight: 500,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        borderRadius: 18,
        border: '1px solid var(--frya-outline-variant)',
        background: 'transparent',
        color: 'var(--frya-on-surface)',
        cursor: 'pointer',
        transition: 'background 150ms, border-color 150ms',
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
      <span
        className="material-symbols-rounded"
        style={{
          fontSize: 16,
          fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 16",
        }}
      >
        {icon}
      </span>
      {label}
    </button>
  )
}

function buildPrompt(data: GreetingResponse | null): string | null {
  if (!data) return null

  // Don't repeat urgent text — the red box shows that separately
  const summary = data.status_summary
  if (!summary) return null

  // Show status_summary as-is (it's already a nice German sentence)
  if (summary.length < 80) return summary

  return 'Was kann ich für dich tun?'
}
