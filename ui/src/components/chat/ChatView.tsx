import { useState, useCallback } from 'react'
import { ChatHistory } from './ChatHistory'
import { ChatInputBar } from './ChatInputBar'
import { useFryaStore } from '../../stores/fryaStore'
import { useTheme } from '../../hooks/useTheme'
import { BugReportOverlay } from '../layout/BugReportOverlay'
import { api } from '../../lib/api'

function ChatTopBar() {
  const goHome = useFryaStore((s) => s.goHome)
  const openSettings = useFryaStore((s) => s.openSettings)
  const { theme, setTheme } = useTheme()
  const [bugOpen, setBugOpen] = useState(false)
  const [screenshot, setScreenshot] = useState<string | null>(null)

  const handleBugReport = useCallback(async () => {
    try {
      const el = document.getElementById('root')
      if (el) {
        const { default: html2canvas } = await import('html2canvas')
        const canvas = await html2canvas(el, {
          backgroundColor: null, scale: 1, logging: false, useCORS: true,
          ignoreElements: (e) => e.getAttribute('data-bug-fab') === 'true',
        })
        setScreenshot(canvas.toDataURL('image/jpeg', 0.7))
      }
    } catch { setScreenshot(null) }
    setBugOpen(true)
  }, [])

  const btnStyle: React.CSSProperties = {
    width: 32, height: 32, borderRadius: 8,
    border: 'none', background: 'transparent',
    color: 'var(--frya-on-surface-variant)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    cursor: 'pointer', flexShrink: 0,
    transition: 'color 0.15s, background 0.15s',
  }

  const onEnter = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.currentTarget.style.color = 'var(--frya-primary)'
    e.currentTarget.style.background = 'var(--frya-surface-container)'
  }
  const onLeave = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.currentTarget.style.color = 'var(--frya-on-surface-variant)'
    e.currentTarget.style.background = 'transparent'
  }

  return (
    <>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          padding: '6px 12px',
          background: 'var(--frya-surface)',
          borderBottom: '1px solid var(--frya-outline-variant)',
          flexShrink: 0,
        }}
      >
        {/* Back */}
        <button onClick={goHome} style={btnStyle} onMouseEnter={onEnter} onMouseLeave={onLeave} aria-label="Zur Startseite">
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>arrow_back</span>
        </button>

        <div style={{ flex: 1 }} />

        {/* Theme — 3-Tasten Segmented Control */}
        <div style={{ display: 'flex', gap: 1, background: 'var(--frya-surface-container)', borderRadius: 10, padding: 2 }}>
          {([
            ['dark', 'dark_mode', 'Dunkel'],
            ['light', 'light_mode', 'Hell'],
            ['system', 'brightness_auto', 'Auto'],
          ] as const).map(([val, icon, label]) => (
            <button
              key={val}
              onClick={() => setTheme(val)}
              title={label}
              style={{
                width: 28, height: 26, borderRadius: 8, border: 'none',
                background: theme === val ? 'var(--frya-primary-container)' : 'transparent',
                color: theme === val ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface-variant)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', transition: 'all 0.15s',
              }}
              aria-label={label}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 15 }}>{icon}</span>
            </button>
          ))}
        </div>

        {/* Bug Report */}
        <button onClick={handleBugReport} style={btnStyle} onMouseEnter={onEnter} onMouseLeave={onLeave} aria-label="Problem melden">
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>bug_report</span>
        </button>

        {/* Settings */}
        <button onClick={openSettings} style={btnStyle} onMouseEnter={onEnter} onMouseLeave={onLeave} aria-label="Einstellungen">
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>settings</span>
        </button>
      </div>

      <BugReportOverlay open={bugOpen} onClose={() => { setBugOpen(false); setScreenshot(null) }} screenshot={screenshot} />
    </>
  )
}

export function ChatView() {
  const [dragOver, setDragOver] = useState(false)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)
  }, [])

  const addFryaMessage = useFryaStore((s) => s.addFryaMessage)

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    const label = `${files.length} Beleg${files.length > 1 ? 'e' : ''}`
    addUserMessage(`\u{1F4CE} ${label} hochgeladen`)

    try {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      await api.postFormData('/documents/bulk-upload', form)
      addFryaMessage({ text: `Alles klar! ${label} empfangen. Ich analysiere das jetzt.` })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload fehlgeschlagen'
      addFryaMessage({ text: `Upload fehlgeschlagen: ${msg}. Bitte versuche es erneut.` })
    }
  }, [addUserMessage, addFryaMessage])

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        height: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--frya-surface)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 50,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 12,
            background: 'rgba(0, 0, 0, 0.6)',
            border: '3px dashed var(--frya-primary)',
            borderRadius: 16,
            margin: 12,
            pointerEvents: 'none',
          }}
        >
          <span
            className="material-symbols-rounded"
            style={{
              fontSize: 48,
              color: 'var(--frya-primary)',
              fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 48",
            }}
          >
            cloud_upload
          </span>
          <span
            style={{
              fontSize: 16,
              fontWeight: 600,
              color: 'var(--frya-on-surface)',
              fontFamily: "'Plus Jakarta Sans', sans-serif",
            }}
          >
            Belege hier reinwerfen
          </span>
        </div>
      )}

      {/* Top bar with home button */}
      <ChatTopBar />

      <ChatHistory />
      <ChatInputBar />
    </div>
  )
}
