import { useState, useEffect } from 'react'
import { Icon, Button } from '../components/m3'
import { api } from '../lib/api'

function getSystemInfo(): Record<string, string> {
  return {
    userAgent: navigator.userAgent,
    language: navigator.language,
    screen: `${screen.width}x${screen.height}`,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    url: window.location.href,
    timestamp: new Date().toISOString(),
  }
}

export function FeedbackPage() {
  const [text, setText] = useState('')
  const [screenshot, setScreenshot] = useState<string | null>(null)
  const [includeScreenshot, setIncludeScreenshot] = useState(true)
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load pre-captured screenshot (taken by BugReportFAB before navigating here)
  useEffect(() => {
    const saved = sessionStorage.getItem('frya-bug-screenshot')
    if (saved) {
      setScreenshot(saved)
      sessionStorage.removeItem('frya-bug-screenshot')
    }
  }, [])

  const canSend = text.trim().length > 0 && !sending

  const handleSubmit = async () => {
    if (!canSend) return
    setSending(true)
    setError(null)
    try {
      const sysInfo = getSystemInfo()
      const payload: Record<string, unknown> = {
        description: text.trim(),
        current_page: sysInfo.url,
      }
      // Note: screenshot + system info could be added when backend supports it
      await api.post('/feedback', payload)
      setDone(true)
      setText('')
      setScreenshot(null)
    } catch {
      setError('Feedback konnte nicht gesendet werden. Bitte versuche es erneut.')
    } finally {
      setSending(false)
    }
  }

  const resetForm = () => {
    setDone(false)
    setText('')
    setScreenshot(null)
    setIncludeScreenshot(true)
    setError(null)
  }

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="bg-surface-container flex items-center gap-3 px-5 py-4">
        <Icon name="bug_report" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Problem melden</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-5">
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
          <div className="space-y-5">
            {/* Screenshot preview (auto-captured from previous page) */}
            {screenshot && (
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 cursor-pointer text-sm text-on-surface">
                    <input
                      type="checkbox"
                      checked={includeScreenshot}
                      onChange={(e) => setIncludeScreenshot(e.target.checked)}
                      className="w-4 h-4 accent-[var(--frya-primary)]"
                    />
                    Screenshot mitsenden
                  </label>
                </div>
                {includeScreenshot && (
                  <>
                    <img
                      src={screenshot}
                      alt="Screenshot der vorherigen Seite"
                      className="w-full rounded-m3 border border-outline-variant"
                      style={{ maxHeight: '180px', objectFit: 'contain', opacity: 0.9 }}
                    />
                    <p className="text-[11px] text-on-surface-variant opacity-50">
                      Nur der FRYA-Inhalt wurde erfasst, nicht dein gesamter Bildschirm.
                    </p>
                  </>
                )}
              </div>
            )}

            {/* Textarea */}
            <div>
              <label className="block text-sm font-medium text-on-surface mb-2">
                Was ist passiert?
              </label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={4}
                placeholder="Beschreibe das Problem..."
                autoFocus
                className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3 border border-outline-variant focus:border-primary focus:outline-none transition-colors resize-y min-h-[100px] text-sm"
              />
            </div>

            {/* System info hint */}
            <p className="text-[11px] text-on-surface-variant opacity-50">
              Geraeteinformationen (Browser, Bildschirmgroesse) werden automatisch mitgesendet.
            </p>

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 px-4 py-2.5 bg-error-container text-error text-xs rounded-m3">
                <Icon name="error" size={16} />
                {error}
              </div>
            )}

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
