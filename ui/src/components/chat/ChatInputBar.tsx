import { useState, useRef } from 'react'
import { Capacitor } from '@capacitor/core'
import { api } from '../../lib/api'
import { useFryaStore } from '../../stores/fryaStore'
import FryaScanner from '../../plugins/scanner'

interface ChatInputBarProps {
  onSend?: (text: string) => void
  placeholder?: string
  disabled?: boolean
}

function base64ToBlob(base64: string, mime: string): Blob {
  const bytes = atob(base64)
  const arr = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

export function ChatInputBar({ onSend, placeholder, disabled }: ChatInputBarProps) {
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [focused, setFocused] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)
  const send = useFryaStore((s) => s.send)
  const addFryaMessage = useFryaStore((s) => s.addFryaMessage)

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
    const fileArray = Array.from(files)

    // Check file sizes before uploading (max 20 MB each)
    const tooLarge = fileArray.filter(f => f.size > 20 * 1024 * 1024)
    if (tooLarge.length > 0) {
      addFryaMessage({ text: `Datei zu groß: "${tooLarge[0].name}" (max. 20 MB). Bitte komprimiere die Datei und versuche es erneut.` })
      if (fileRef.current) fileRef.current.value = ''
      return
    }

    const label = `${fileArray.length} Beleg${fileArray.length > 1 ? 'e' : ''}`
    setUploading(true)
    addUserMessage(`${label} hochgeladen`)
    useFryaStore.getState().startChat()
    try {
      const form = new FormData()
      fileArray.forEach((f) => form.append('files', f))
      await api.postFormData('/documents/bulk-upload', form)
      addFryaMessage({ text: `Alles klar! ${label} empfangen. Ich analysiere das jetzt.` })
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err)
      // Specific error messages for common problems
      if (errMsg.includes('413')) {
        addFryaMessage({ text: `Datei zu groß fuer den Upload. Bitte nutze Dateien unter 20 MB.` })
      } else if (errMsg.includes('fetch') || errMsg.includes('network') || errMsg.toLowerCase().includes('failed')) {
        addFryaMessage({ text: `Upload fehlgeschlagen. Falls du eine Datei aus Google Drive ausgewaehlt hast: Stelle sicher, dass die Datei zuvor heruntergeladen wurde (Offline verfuegbar). Dann erneut versuchen.` })
      } else {
        addFryaMessage({ text: `Upload fehlgeschlagen: ${errMsg}. Bitte versuche es erneut.` })
      }
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // Native ML Kit Document Scanner
  const handleScan = async () => {
    if (!Capacitor.isNativePlatform()) {
      // Web-Fallback: normaler File-Upload
      fileRef.current?.click()
      return
    }
    setScanning(true)
    addUserMessage('Beleg wird gescannt…')
    useFryaStore.getState().startChat()
    try {
      const result = await FryaScanner.scan({ pageLimit: 20, enableGalleryImport: true })
      if (result.pdfBase64) {
        const blob = base64ToBlob(result.pdfBase64, 'application/pdf')
        const form = new FormData()
        form.append('files', blob, `scan-${Date.now()}.pdf`)
        await api.postFormData('/documents/bulk-upload', form)
        addFryaMessage({
          text: `Scan erfolgreich! ${result.pageCount} Seite${result.pageCount !== 1 ? 'n' : ''} empfangen. Ich analysiere das jetzt.`,
        })
      } else {
        addFryaMessage({ text: 'Scan abgeschlossen, aber kein PDF erhalten.' })
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('abgebrochen')) {
        addFryaMessage({ text: 'Scan abgebrochen.' })
      } else {
        addFryaMessage({ text: `Scan fehlgeschlagen: ${msg}` })
      }
    } finally {
      setScanning(false)
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

  const busy = uploading || scanning

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
        {/* Attach button (immer sichtbar) */}
        <button
          onClick={() => fileRef.current?.click()}
          disabled={disabled || busy}
          style={{
            ...iconStyle,
            color: 'var(--frya-on-surface-variant)',
            opacity: disabled || busy ? 0.3 : 1,
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

        {/* Scanner-Button — NUR in der nativen App */}
        {Capacitor.isNativePlatform() && (
          <button
            onClick={handleScan}
            disabled={disabled || busy}
            style={{
              ...iconStyle,
              color: 'var(--frya-primary)',
              opacity: disabled || busy ? 0.3 : 1,
            }}
            aria-label="Beleg scannen"
          >
            <span
              className="material-symbols-rounded"
              style={{
                fontSize: 20,
                fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 20",
              }}
            >
              {scanning ? 'hourglass_top' : 'document_scanner'}
            </span>
          </button>
        )}

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
