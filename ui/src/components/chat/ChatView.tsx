import { useState, useCallback } from 'react'
import { ChatHistory } from './ChatHistory'
import { ChatInputBar } from './ChatInputBar'
import { useFryaStore } from '../../stores/fryaStore'
import { api } from '../../lib/api'

function ChatTopBar() {
  const goHome = useFryaStore((s) => s.goHome)

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 16px',
        background: 'var(--frya-surface)',
        flexShrink: 0,
      }}
    >
      <button
        onClick={goHome}
        style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          border: 'none',
          background: 'transparent',
          color: 'var(--frya-on-surface-variant)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          flexShrink: 0,
          transition: 'color 0.15s, background 0.15s',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--frya-primary)'
          e.currentTarget.style.background = 'var(--frya-surface-container)'
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--frya-on-surface-variant)'
          e.currentTarget.style.background = 'transparent'
        }}
        aria-label="Zur Startseite"
      >
        <span
          className="material-symbols-rounded"
          style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 18" }}
        >
          arrow_back
        </span>
      </button>
    </div>
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

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    try {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      await api.postFormData('/documents/bulk-upload', form)
      addUserMessage(`\u{1F4CE} ${files.length} Beleg${files.length > 1 ? 'e' : ''} hochgeladen`)
    } catch {
      // Error handled by API client
    }
  }, [addUserMessage])

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--frya-surface)',
        position: 'relative',
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
