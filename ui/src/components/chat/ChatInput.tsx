import { useState, useRef } from 'react'
import { Icon } from '../m3'
import { api } from '../../lib/api'

interface ChatInputProps {
  onSend: (text: string) => void
  onFileUploaded?: (file: File) => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({ onSend, onFileUploaded, disabled, placeholder }: ChatInputProps) {
  const [text, setText] = useState('')
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    inputRef.current?.focus()
  }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await api.upload('/documents/upload', file)
      onFileUploaded?.(file)
    } catch {
      // Error handled by api client
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="flex items-center gap-2 p-3 bg-surface-container border-t border-outline-variant/50">
      {/* File upload */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*,.pdf,.jpg,.jpeg,.png"
        className="hidden"
        onChange={handleFile}
      />
      <button
        onClick={() => fileRef.current?.click()}
        disabled={disabled || uploading}
        className="w-10 h-10 flex items-center justify-center rounded-full text-on-surface-variant hover:bg-surface-container-high disabled:opacity-30 transition-colors"
        aria-label="Datei anhängen"
      >
        <Icon name={uploading ? 'hourglass_top' : 'attach_file'} size={20} />
      </button>

      {/* Text input */}
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
        placeholder={placeholder || 'Nachricht an Frya…'}
        className="flex-1 px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-xl border-none focus:outline-none focus:ring-2 focus:ring-primary/30 text-sm placeholder:text-on-surface-variant/50"
        disabled={disabled}
      />

      {/* Mic placeholder (Phase 2) */}
      <button
        disabled
        className="w-10 h-10 flex items-center justify-center rounded-full text-on-surface-variant/30"
        aria-label="Spracheingabe (bald verfügbar)"
        title="Spracheingabe — Phase 2"
      >
        <Icon name="mic" size={20} />
      </button>

      {/* Send */}
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className="w-12 h-12 flex items-center justify-center rounded-full bg-primary text-on-primary disabled:opacity-30 transition-opacity"
        aria-label="Senden"
      >
        <Icon name="send" size={20} />
      </button>
    </div>
  )
}
