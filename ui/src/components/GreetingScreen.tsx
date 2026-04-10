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

  // Parse inbox count from status_summary (e.g. "10 Belege in der Inbox")
  const inboxCount = (() => {
    const summary = data?.status_summary || ''
    const match = summary.match(/(\d+)\s*Belege/i)
    return match ? parseInt(match[1], 10) : 0
  })()

  const statusText = buildPrompt(data)

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--frya-surface)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Subtiles Pixel-Grid-Hintergrundmuster — fast unsichtbar */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundImage: [
            'linear-gradient(var(--frya-outline-variant) 1px, transparent 1px)',
            'linear-gradient(90deg, var(--frya-outline-variant) 1px, transparent 1px)',
          ].join(', '),
          backgroundSize: '4px 4px',
          opacity: 0.03,
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      {/* Top bar — BugReport + Settings oben rechts */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', padding: '8px 12px', gap: 4, flexShrink: 0, position: 'relative', zIndex: 1 }}>
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

      {/* Content — 15vh von oben, nicht vertikal zentriert */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'flex-start',
          paddingTop: '15vh',
          paddingLeft: 20,
          paddingRight: 20,
          paddingBottom: 80,
          overflow: 'auto',
          position: 'relative',
          zIndex: 1,
        }}
      >
        <div style={{ maxWidth: 440, width: '100%', textAlign: 'center' }}>

          {/* Avatar — 160px, App-Icon-Form mit Pixel-Art-Schatten */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginBottom: 20,
              animation: 'frya-fade-up 400ms ease both',
            }}
          >
            <FryaAvatar
              size={160}
              style={{
                borderRadius: 40,
                boxShadow: '4px 4px 0px var(--frya-primary-container), 8px 8px 0px rgba(0,0,0,0.1)',
              }}
            />
          </div>

          {/* Greeting text */}
          {loading ? (
            <div style={{ marginBottom: 24 }}>
              <div
                style={{
                  height: 34,
                  width: 200,
                  background: 'var(--frya-surface-container-high)',
                  borderRadius: 8,
                  margin: '0 auto 12px',
                  animation: 'frya-pulse 1.5s ease-in-out infinite',
                }}
              />
              <div
                style={{
                  height: 18,
                  width: 260,
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
                marginBottom: 24,
                animation: 'frya-fade-up 400ms ease 100ms both',
              }}
            >
              <h1
                style={{
                  fontFamily: "'Outfit', sans-serif",
                  fontSize: 32,
                  fontWeight: 600,
                  color: 'var(--frya-on-surface)',
                  letterSpacing: '-0.02em',
                  lineHeight: 1.15,
                  margin: '0 0 10px',
                }}
              >
                {data?.greeting || 'Hallo!'}
              </h1>

              {statusText && (
                <p
                  style={{
                    fontSize: 16,
                    color: 'var(--frya-on-surface-variant)',
                    lineHeight: 1.5,
                    maxWidth: 280,
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
            <div style={{ marginBottom: 16, animation: 'frya-fade-up 400ms ease 200ms both' }}>
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

          {/* Primaere Aktionen — volle Breite, vertikal gestapelt */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              width: '100%',
              maxWidth: 320,
              margin: '0 auto',
              animation: 'frya-fade-up 400ms ease 250ms both',
            }}
          >
            <PrimaryChip
              icon="inbox"
              label="Inbox"
              badge={inboxCount > 0 ? inboxCount : undefined}
              onClick={() => handleChip('Inbox')}
            />
            <PrimaryChip
              icon="bar_chart"
              label="Finanzen"
              onClick={() => handleChip('Finanzen')}
            />
            <PrimaryChip
              icon="cloud_upload"
              label="Belege einwerfen"
              onClick={() => handleChip('Belege einwerfen')}
            />
          </div>

          {/* Sekundaere Aktionen — kleiner, weniger prominent */}
          <div
            style={{
              display: 'flex',
              gap: 8,
              justifyContent: 'center',
              flexWrap: 'wrap',
              marginTop: 12,
              animation: 'frya-fade-up 400ms ease 300ms both',
            }}
          >
            <SecondaryChip label="EÜR" onClick={() => handleChip('EÜR')} />
            <SecondaryChip label="Fristen" onClick={() => handleChip('Fristen')} />
            <SecondaryChip label="Export" onClick={() => handleChip('Export')} />
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

interface PrimaryChipProps {
  icon: string
  label: string
  badge?: number
  onClick: () => void
}

function PrimaryChip({ icon, label, badge, onClick }: PrimaryChipProps) {
  const [hovered, setHovered] = useState(false)
  const [pressed, setPressed] = useState(false)

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setPressed(false) }}
      onMouseDown={() => setPressed(true)}
      onMouseUp={() => setPressed(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '14px 20px',
        borderRadius: 16,
        background: hovered ? 'var(--frya-primary-container)' : 'var(--frya-surface-container-high)',
        border: `1.5px solid ${hovered ? 'var(--frya-primary)' : 'var(--frya-outline-variant)'}`,
        color: hovered ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface)',
        fontSize: 15,
        fontWeight: 500,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        boxShadow: pressed
          ? '0px 0px 0px var(--frya-outline-variant)'
          : hovered
            ? '3px 3px 0px var(--frya-primary-container)'
            : '2px 2px 0px var(--frya-outline-variant)',
        transform: pressed ? 'translate(2px, 2px)' : 'translate(0, 0)',
        width: '100%',
        textAlign: 'left',
      }}
    >
      <span
        className="material-symbols-rounded"
        style={{
          fontSize: 20,
          fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20",
          flexShrink: 0,
        }}
      >
        {icon}
      </span>
      <span style={{ flex: 1 }}>{label}</span>
      {badge !== undefined && (
        <span
          style={{
            background: 'var(--frya-primary)',
            color: 'var(--frya-on-primary)',
            fontSize: 11,
            fontWeight: 600,
            padding: '2px 7px',
            borderRadius: 10,
            flexShrink: 0,
          }}
        >
          {badge}
        </span>
      )}
    </button>
  )
}

function SecondaryChip({ label, onClick }: { label: string; onClick: () => void }) {
  const [hovered, setHovered] = useState(false)

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        padding: '8px 16px',
        borderRadius: 12,
        background: hovered ? 'var(--frya-surface-container-high)' : 'transparent',
        border: `1px solid ${hovered ? 'var(--frya-primary)' : 'var(--frya-outline-variant)'}`,
        color: 'var(--frya-on-surface-variant)',
        fontSize: 13,
        fontWeight: 400,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        cursor: 'pointer',
        transition: 'all 0.15s ease',
      }}
    >
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
