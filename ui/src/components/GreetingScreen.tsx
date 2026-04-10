import { useEffect, useState, useCallback } from 'react'
import { BugReportOverlay } from './layout/BugReportOverlay'
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
      {/* Warm radial ambient glow — oben zentriert, subtil */}
      <div
        style={{
          position: 'absolute',
          top: '-10%',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '120vw',
          height: '60vh',
          background: 'radial-gradient(ellipse at center top, rgba(251, 146, 60, 0.07) 0%, transparent 70%)',
          pointerEvents: 'none',
          zIndex: 0,
        }}
      />

      {/* Top bar — BugReport + Settings oben rechts */}
      <div style={{
        display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
        padding: '10px 14px', gap: 4, flexShrink: 0, position: 'relative', zIndex: 1,
      }}>
        <button
          onClick={handleBugReport}
          style={{
            width: 34, height: 34, borderRadius: 10, border: 'none',
            background: 'transparent', color: 'var(--frya-on-surface-variant)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
            transition: 'background 150ms',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--frya-surface-container)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
          aria-label="Problem melden"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>bug_report</span>
        </button>
        <button
          onClick={() => useFryaStore.getState().openSettings()}
          style={{
            width: 34, height: 34, borderRadius: 10, border: 'none',
            background: 'transparent', color: 'var(--frya-on-surface-variant)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer',
            transition: 'background 150ms',
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--frya-surface-container)' }}
          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
          aria-label="Einstellungen"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>settings</span>
        </button>
      </div>

      {/* Content — 12vh von oben, nicht vertikal zentriert */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'flex-start',
          paddingTop: '12vh',
          paddingLeft: 20,
          paddingRight: 20,
          paddingBottom: 80,
          overflow: 'auto',
          position: 'relative',
          zIndex: 1,
        }}
      >
        <div style={{ maxWidth: 400, width: '100%', textAlign: 'center' }}>

          {/* ── Avatar — 220px, kein Hintergrund, Pixel-Art-Glow ── */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginBottom: 24,
              animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) both',
            }}
          >
            <img
              src="/frya-avatar.png"
              alt="Frya"
              style={{
                width: 220,
                height: 220,
                objectFit: 'contain',
                // Warmer Glow — passt zu Fryas Orangerot-Farbpalette
                filter: [
                  'drop-shadow(0 0 18px rgba(251, 146, 60, 0.45))',
                  'drop-shadow(0 0 6px rgba(251, 146, 60, 0.25))',
                ].join(' '),
              }}
            />
          </div>

          {/* ── Greeting ── */}
          {loading ? (
            <div style={{ marginBottom: 28 }}>
              <div style={{
                height: 36, width: 220, background: 'var(--frya-surface-container-high)',
                borderRadius: 10, margin: '0 auto 14px',
                animation: 'frya-pulse 1.5s ease-in-out infinite',
              }} />
              <div style={{
                height: 18, width: 270, background: 'var(--frya-surface-container-high)',
                borderRadius: 8, margin: '0 auto', opacity: 0.6,
                animation: 'frya-pulse 1.5s ease-in-out infinite 200ms',
              }} />
            </div>
          ) : (
            <div style={{ marginBottom: 28, animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) 80ms both' }}>
              <h1 style={{
                fontFamily: "'Outfit', sans-serif",
                fontSize: 34,
                fontWeight: 700,
                color: 'var(--frya-on-surface)',
                letterSpacing: '-0.03em',
                lineHeight: 1.1,
                margin: '0 0 10px',
              }}>
                {data?.greeting || 'Hallo!'}
              </h1>
              {statusText && (
                <p style={{
                  fontSize: 16,
                  color: 'var(--frya-on-surface-variant)',
                  lineHeight: 1.55,
                  maxWidth: 260,
                  margin: '0 auto',
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  fontWeight: 400,
                }}>
                  {statusText}
                </p>
              )}
            </div>
          )}

          {/* ── Urgent banner ── */}
          {data?.urgent && data.urgent.priority === 'HIGH' && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'var(--frya-warning-container)', color: 'var(--frya-warning)',
              borderRadius: 14, padding: '10px 16px', marginBottom: 20,
              fontSize: 13, fontFamily: "'Plus Jakarta Sans', sans-serif", textAlign: 'left',
              animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) 150ms both',
            }}>
              <span className="material-symbols-rounded" style={{
                fontSize: 18, flexShrink: 0,
                fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 18",
              }}>warning</span>
              <span>{data.urgent.text}</span>
            </div>
          )}

          {/* ── Back to chat button ── */}
          {messageCount > 0 && (
            <div style={{ marginBottom: 20, animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) 150ms both' }}>
              <button
                onClick={() => startChat()}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 8,
                  padding: '11px 22px', fontSize: 13, fontWeight: 600,
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
                  borderRadius: 22, border: 'none',
                  background: 'var(--frya-primary)', color: 'var(--frya-on-primary)',
                  cursor: 'pointer', boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                }}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>chat</span>
                Zurück zum Chat ({messageCount})
              </button>
            </div>
          )}

          {/* ── Primaere Aktionen — volle Breite, vertikal ── */}
          <div style={{
            display: 'flex', flexDirection: 'column', gap: 10,
            width: '100%', maxWidth: 320, margin: '0 auto',
            animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) 200ms both',
          }}>
            <PrimaryChip icon="inbox" label="Inbox" badge={inboxCount > 0 ? inboxCount : undefined} onClick={() => handleChip('Inbox')} />
            <PrimaryChip icon="bar_chart" label="Finanzen" onClick={() => handleChip('Finanzen')} />
            <PrimaryChip icon="cloud_upload" label="Belege einwerfen" onClick={() => handleChip('Belege einwerfen')} />
          </div>

          {/* ── Sekundaere Aktionen ── */}
          <div style={{
            display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap',
            marginTop: 12,
            animation: 'frya-fade-up 500ms cubic-bezier(0.16, 1, 0.3, 1) 280ms both',
          }}>
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
          50% { opacity: 0.4; }
        }
      `}</style>
    </div>
  )
}

// ── PrimaryChip ──────────────────────────────────────────────────────────────

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
        gap: 12,
        padding: '15px 20px',
        borderRadius: 18,
        background: hovered ? 'var(--frya-primary-container)' : 'var(--frya-surface-container-high)',
        border: `1.5px solid ${hovered ? 'var(--frya-primary)' : 'var(--frya-outline-variant)'}`,
        color: hovered ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface)',
        fontSize: 15,
        fontWeight: 500,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        cursor: 'pointer',
        transition: 'all 0.15s ease',
        // Pixel-Art Schatten
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
      <span className="material-symbols-rounded" style={{
        fontSize: 20,
        fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20",
        flexShrink: 0,
        color: hovered ? 'var(--frya-on-primary-container)' : 'var(--frya-primary)',
      }}>
        {icon}
      </span>
      <span style={{ flex: 1 }}>{label}</span>
      {badge !== undefined && (
        <span style={{
          background: 'var(--frya-primary)', color: 'var(--frya-on-primary)',
          fontSize: 11, fontWeight: 700, padding: '2px 8px',
          borderRadius: 12, flexShrink: 0,
          fontFamily: "'Plus Jakarta Sans', sans-serif",
        }}>
          {badge}
        </span>
      )}
    </button>
  )
}

// ── SecondaryChip ────────────────────────────────────────────────────────────

function SecondaryChip({ label, onClick }: { label: string; onClick: () => void }) {
  const [hovered, setHovered] = useState(false)

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        padding: '8px 18px', borderRadius: 14,
        background: hovered ? 'var(--frya-surface-container-high)' : 'transparent',
        border: `1px solid ${hovered ? 'var(--frya-primary)' : 'var(--frya-outline-variant)'}`,
        color: hovered ? 'var(--frya-on-surface)' : 'var(--frya-on-surface-variant)',
        fontSize: 13, fontWeight: 400,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
        cursor: 'pointer', transition: 'all 0.15s ease',
      }}
    >
      {label}
    </button>
  )
}

// ── buildPrompt ──────────────────────────────────────────────────────────────

function buildPrompt(data: GreetingResponse | null): string | null {
  if (!data) return null
  const summary = data.status_summary
  if (!summary) return null
  if (summary.length < 80) return summary
  return 'Was kann ich für dich tun?'
}
