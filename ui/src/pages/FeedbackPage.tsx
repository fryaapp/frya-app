import { useState, useRef } from 'react'
import { Icon, Button } from '../components/m3'
import { api } from '../lib/api'

export function FeedbackPage() {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const canSend = text.trim().length > 0 && !sending

  const handleSubmit = async () => {
    if (!canSend) return
    setSending(true)
    try {
      const form = new FormData()
      form.append('description', text.trim())
      form.append('current_page', window.location.pathname)
      if (file) form.append('screenshot', file)
      await api.postFormData('/feedback', form)
      setDone(true)
      setText('')
      setFile(null)
    } catch {
      /* silent — could add error toast later */
    } finally {
      setSending(false)
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    setFile(picked)
  }

  const resetForm = () => {
    setDone(false)
    setText('')
    setFile(null)
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 bg-surface-container">
        <Icon name="bug_report" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Problem melden</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {done ? (
          <div className="flex flex-col items-center justify-center gap-4 py-16">
            <Icon name="check_circle" size={56} className="text-success" />
            <p className="text-base font-semibold text-on-surface text-center">
              Danke! Dein Feedback wurde gesendet.
            </p>
            <Button variant="tonal" icon="edit" onClick={resetForm}>
              Weiteres Feedback
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Textarea */}
            <div>
              <label className="block text-sm font-medium text-on-surface-variant mb-1">
                Beschreibe das Problem
              </label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={4}
                placeholder="Beschreibe das Problem..."
                className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors resize-y min-h-[100px] text-sm"
              />
            </div>

            {/* Screenshot */}
            <div>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                onChange={handleFileChange}
                className="hidden"
              />
              <Button
                variant="tonal"
                icon="photo_camera"
                onClick={() => fileRef.current?.click()}
                className="w-full"
              >
                Screenshot anhängen
              </Button>
              {file && (
                <div className="flex items-center gap-2 mt-2 text-xs text-on-surface-variant">
                  <Icon name="image" size={16} />
                  <span className="truncate flex-1">{file.name}</span>
                  <button
                    type="button"
                    onClick={() => setFile(null)}
                    className="text-error hover:opacity-70"
                  >
                    <Icon name="close" size={16} />
                  </button>
                </div>
              )}
            </div>

            {/* Submit */}
            <Button
              variant="filled"
              icon="send"
              onClick={handleSubmit}
              disabled={!canSend}
              className="w-full"
            >
              {sending ? 'Wird gesendet...' : 'Absenden'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
