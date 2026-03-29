import { useState, useRef } from 'react'
import { api } from '../../lib/api'
import { useFryaStore } from '../../stores/fryaStore'

interface ChatInputBarProps {
  onSend?: (text: string) => void
  placeholder?: string
  disabled?: boolean
}

export function ChatInputBar({ onSend, placeholder, disabled }: ChatInputBarProps) {
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)
  const send = useFryaStore((s) => s.send)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    if (onSend) {
      onSend(trimmed)
    } else {
      addUserMessage(trimmed)
      send({ text: trimmed })
    }
    setText('')
    inputRef.current?.focus()
  }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    setUploading(true)
    try {
      const fileArray = Array.from(files)
      const form = new FormData()
      fileArray.forEach((f) => form.append('files', f))
      await api.postFormData('/documents/bulk-upload', form)
      addUserMessage(`\u{1F4CE} ${fileArray.length} Beleg${fileArray.length > 1 ? 'e' : ''} hochgeladen`)
    } catch {
      // Error handled by API client
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const iconStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 36,
    height: 36,
    borderRadius: '50%',
    border: 'none',
    background: 'transparent',
    cursor: 'pointer',
    flexShrink: 0,
    transition: 'background 150ms',
  }

  return (
    <div
      style={{
        padding: '8px 16px 16px',
        borderTop: '1px solid var(--frya-outline-variant)',
        maxWidth: 720,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box',
      }}
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/*,application/pdf"
        multiple
        style={{ display: 'none' }}
        onChange={handleFile}
      />

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          background: 'var(--frya-surface-container-low)',
          border: `1.5px solid ${focused ? 'var(--frya-primary)' : 'var(--frya-outline-variant)'}`,
          borderRadius: 24,
          padding: '4px 6px 4px 14px',
          transition: 'border-color 200ms',
        }}
      >
        {/* Attach button */}
        <button
          onClick={() => fileRef.current?.click()}
          disabled={disabled || uploading}
          style={{
            ...iconStyle,
            color: 'var(--frya-on-surface-variant)',
            opacity: disabled || uploading ? 0.3 : 1,
          }}
          aria-label="Datei anhaengen"
        >
          <span
            className="material-symbols-rounded"
            style={{
              fontSize: 20,
              fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20",
            }}
          >
            {uploading ? 'hourglass_top' : 'attach_file'}
          </span>
        </button>

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={placeholder || 'Nachricht an Frya\u2026'}
          disabled={disabled}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            color: 'var(--frya-on-surface)',
            fontSize: 14,
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            padding: '8px 0',
            minWidth: 0,
          }}
        />

        {/* Send button */}
        <button
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          style={{
            ...iconStyle,
            color: 'var(--frya-primary)',
            opacity: disabled || !text.trim() ? 0.3 : 1,
          }}
          aria-label="Senden"
        >
          <span
            className="material-symbols-rounded"
            style={{
              fontSize: 20,
              fontVariationSettings: "'FILL' 1, 'wght' 400, 'GRAD' 0, 'opsz' 20",
            }}
          >
            send
          </span>
        </button>
      </div>
    </div>
  )
}
