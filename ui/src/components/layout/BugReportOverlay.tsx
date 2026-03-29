import { useState, useEffect, useCallback } from 'react'
import { Icon, Button } from '../m3'
import { api } from '../../lib/api'

/**
 * BugReportOverlay — Completely independent bug-reporting system.
 *
 * ✅ Renders as a fixed overlay (z-index 9999) — NOT inside the router/SplitView
 * ✅ Works from ANY page, even if the app is broken or hung
 * ✅ Captures screenshot BEFORE opening the modal
 * ✅ Minimal own state — doesn't depend on any store or context
 */

interface BugReportOverlayProps {
  open: boolean
  onClose: () => void
  screenshot: string | null
}

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

export function BugReportOverlay({ open, onClose, screenshot }: BugReportOverlayProps) {
  const [text, setText] = useState('')
  const [includeScreenshot, setIncludeScreenshot] = useState(true)
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opened
  useEffect(() => {
    if (open) {
      setText('')
      setDone(false)
      setError(null)
      setIncludeScreenshot(true)
    }
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  const handleSubmit = async () => {
    if (!text.trim() || sending) return
    setSending(true)
    setError(null)
    try {
      const sysInfo = getSystemInfo()
      const payload: Record<string, unknown> = {
        description: text.trim(),
        current_page: sysInfo.url,
        system_info: sysInfo,
      }
      if (includeScreenshot && screenshot) {
        payload.screenshot = screenshot
      }
      await api.post('/feedback', payload)
      setDone(true)
    } catch {
      setError('Feedback konnte nicht gesendet werden. Bitte versuche es erneut.')
    } finally {
      setSending(false)
    }
  }

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[9998]"
        style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
        onClick={onClose}
      />

      {/* Modal */}
      <div
        className="fixed z-[9999]"
        style={{
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          animation: 'bug-modal-in 0.3s ease both',
          width: 'min(420px, calc(100vw - 32px))',
          maxHeight: '85vh',
          background: 'var(--frya-surface-container-high)',
          borderRadius: '24px',
          border: '1px solid var(--frya-outline-variant)',
          boxShadow: '0 24px 80px rgba(0,0,0,0.5)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '16px 20px',
            borderBottom: '1px solid var(--frya-outline-variant)',
            background: 'var(--frya-surface-container)',
          }}
        >
          <Icon name="bug_report" size={22} className="text-primary" />
          <h2 style={{ flex: 1, fontSize: 16, fontWeight: 700, fontFamily: 'Outfit, sans-serif', color: 'var(--frya-on-surface)' }}>
            Problem melden
          </h2>
          <button
            onClick={onClose}
            style={{
              width: 32, height: 32, borderRadius: '50%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--frya-on-surface-variant)',
            }}
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {done ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: '32px 0' }}>
              <Icon name="check_circle" size={48} className="text-success" />
              <p style={{ fontSize: 15, fontWeight: 600, color: 'var(--frya-on-surface)', textAlign: 'center' }}>
                Danke! Dein Feedback wurde gesendet.
              </p>
              <Button variant="tonal" icon="close" onClick={onClose}>
                Schließen
              </Button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* Screenshot */}
              {screenshot && (
                <div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13, color: 'var(--frya-on-surface)' }}>
                    <input
                      type="checkbox"
                      checked={includeScreenshot}
                      onChange={(e) => setIncludeScreenshot(e.target.checked)}
                      style={{ width: 16, height: 16, accentColor: 'var(--frya-primary)' }}
                    />
                    Screenshot mitsenden
                  </label>
                  {includeScreenshot && (
                    <img
                      src={screenshot}
                      alt="Screenshot"
                      style={{
                        width: '100%', marginTop: 8, borderRadius: 12,
                        border: '1px solid var(--frya-outline-variant)',
                        maxHeight: 160, objectFit: 'contain', opacity: 0.9,
                      }}
                    />
                  )}
                </div>
              )}

              {/* Textarea */}
              <div>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: 'var(--frya-on-surface)', marginBottom: 6 }}>
                  Was ist passiert?
                </label>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={3}
                  placeholder="Beschreibe das Problem..."
                  autoFocus
                  style={{
                    width: '100%', padding: '10px 14px',
                    background: 'var(--frya-surface-container)',
                    color: 'var(--frya-on-surface)',
                    border: '1px solid var(--frya-outline-variant)',
                    borderRadius: 12, fontSize: 14, resize: 'vertical',
                    minHeight: 80, outline: 'none',
                    fontFamily: 'Plus Jakarta Sans, sans-serif',
                  }}
                />
              </div>

              <p style={{ fontSize: 11, color: 'var(--frya-on-surface-variant)', opacity: 0.5 }}>
                Geräteinformationen werden automatisch mitgesendet.
              </p>

              {/* Error */}
              {error && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                  background: 'var(--frya-error-container)', color: 'var(--frya-error)',
                  borderRadius: 10, fontSize: 12,
                }}>
                  <Icon name="error" size={16} />
                  {error}
                </div>
              )}

              {/* Submit */}
              <Button
                variant="filled"
                icon="send"
                onClick={handleSubmit}
                disabled={!text.trim() || sending}
                className="w-full"
              >
                {sending ? 'Wird gesendet...' : 'Absenden'}
              </Button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

/**
 * BugReportFAB — The floating action button that triggers the overlay.
 * Captures screenshot BEFORE opening.
 */
export function BugReportFAB() {
  const [open, setOpen] = useState(false)
  const [screenshot, setScreenshot] = useState<string | null>(null)

  const handleOpen = useCallback(async () => {
    // Capture screenshot BEFORE opening the modal
    try {
      const el = document.getElementById('root')
      if (el) {
        const { default: html2canvas } = await import('html2canvas')
        const canvas = await html2canvas(el, {
          backgroundColor: null,
          scale: 1,
          logging: false,
          useCORS: true,
          ignoreElements: (element) => {
            // Ignore the FAB itself so it doesn't appear in the screenshot
            return element.getAttribute('data-bug-fab') === 'true'
          },
        })
        setScreenshot(canvas.toDataURL('image/jpeg', 0.7))
      }
    } catch {
      setScreenshot(null)
    }
    setOpen(true)
  }, [])

  const handleClose = useCallback(() => {
    setOpen(false)
    setScreenshot(null)
  }, [])

  return (
    <>
      {/* FAB Button */}
      <button
        data-bug-fab="true"
        onClick={handleOpen}
        className="fixed z-[150] w-[34px] h-[34px] rounded-[12px] bg-surface-container-low border border-outline-variant flex items-center justify-center hover:bg-primary-container hover:border-primary transition-all cursor-pointer group"
        style={{ bottom: 18, right: 18 }}
        aria-label="Problem melden"
      >
        <Icon name="bug_report" size={15} className="text-on-surface-variant group-hover:text-primary" />
      </button>

      {/* Overlay Modal — completely independent, fixed position, highest z-index */}
      <BugReportOverlay open={open} onClose={handleClose} screenshot={screenshot} />
    </>
  )
}
