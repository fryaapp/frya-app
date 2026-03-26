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
    <div className="px-4 mb-4">
      {/* Hidden file input */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*,.pdf,.jpg,.jpeg,.png"
        className="hidden"
        onChange={handleFile}
      />

      {/* Pill-shaped input container */}
      <div className="flex items-center gap-1.5 bg-surface-container-low border-[1.5px] border-outline-variant rounded-[26px] pl-[18px] pr-1.5 py-1 transition-all focus-within:border-primary focus-within:bg-surface-container-high">
        {/* Attach icon */}
        <button
          onClick={() => fileRef.current?.click()}
          disabled={disabled || uploading}
          className="shrink-0 w-8 h-8 flex items-center justify-center rounded-full text-on-surface-variant hover:bg-surface-container-high disabled:opacity-30 transition-colors"
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
          className="flex-1 bg-transparent text-on-surface text-sm placeholder:text-on-surface-variant/50 focus:outline-none focus:ring-0 border-none py-2"
          disabled={disabled}
        />

        {/* Send icon */}
        <button
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          className="shrink-0 w-8 h-8 flex items-center justify-center rounded-full text-primary disabled:opacity-30 transition-opacity"
          aria-label="Senden"
        >
          <Icon name="send" size={20} />
        </button>
      </div>
    </div>
  )
}
