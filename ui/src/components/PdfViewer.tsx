/**
 * PdfViewer — Full-screen in-app PDF viewer for Frya.
 *
 * Features:
 *   • Page-by-page rendering via PDF.js (no external viewer needed)
 *   • Swipe left/right to change pages
 *   • Double-tap to toggle 2× zoom
 *   • Top bar: back arrow (same style as ChatTopBar) + title + download button
 *   • Bottom nav: ← page N/M → (hidden for single-page docs)
 *   • Download: triggers browser/OS download of the PDF
 *   • Works in Capacitor WebView on Android and iOS
 */
import { useEffect, useState, useRef, useCallback } from 'react'
import { api } from '../lib/api'

// Worker URL — Vite bundles this as a separate asset, accessible in Capacitor WebView
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

interface PdfViewerProps {
  caseId: string
  title: string
  onClose: () => void
}

// ── Shared button styles (match ChatTopBar) ──────────────────────────────────

const iconBtnBase: React.CSSProperties = {
  width: 36, height: 36, borderRadius: 8,
  border: 'none', background: 'transparent',
  color: 'var(--frya-on-surface-variant)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  cursor: 'pointer', flexShrink: 0,
  transition: 'color 0.15s, background 0.15s',
}

// ── Spinner ──────────────────────────────────────────────────────────────────

function Spinner({ label }: { label: string }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 12,
      color: 'var(--frya-on-surface-variant)',
      fontFamily: "'Plus Jakarta Sans', sans-serif", fontSize: 13,
    }}>
      <span
        className="material-symbols-rounded"
        style={{
          fontSize: 32, animation: 'frya-spin 1s linear infinite',
          fontVariationSettings: "'FILL' 0, 'wght' 300",
        }}
      >
        progress_activity
      </span>
      {label}
    </div>
  )
}

// ── Error state ───────────────────────────────────────────────────────────────

function ErrorState({ message }: { message: string }) {
  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 12,
      color: 'var(--frya-error)',
      fontFamily: "'Plus Jakarta Sans', sans-serif", fontSize: 13,
      padding: 24,
    }}>
      <span className="material-symbols-rounded" style={{ fontSize: 36 }}>error</span>
      {message}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function PdfViewer({ caseId, title, onClose }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pdfDoc, setPdfDoc] = useState<any>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [loading, setLoading] = useState(true)
  const [rendering, setRendering] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [pdfBytes, setPdfBytes] = useState<Uint8Array | null>(null)
  const renderTaskRef = useRef<any>(null)

  // ── Load PDF ──────────────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setPdfDoc(null)
    setCurrentPage(1)
    setTotalPages(0)

    async function load() {
      try {
        const blob = await api.getBlob(`/cases/${caseId}/document`)
        const arrayBuffer = await blob.arrayBuffer()
        const uint8 = new Uint8Array(arrayBuffer)

        if (cancelled) return
        setPdfBytes(uint8)

        // Dynamic import keeps pdfjs-dist out of the main bundle
        const pdfjsLib = await import('pdfjs-dist')
        pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

        const doc = await pdfjsLib.getDocument({ data: uint8 }).promise
        if (cancelled) { doc.destroy(); return }

        setPdfDoc(doc)
        setTotalPages(doc.numPages)
        setLoading(false)
      } catch (err) {
        if (!cancelled) {
          console.error('[PdfViewer] load error', err)
          setError('PDF konnte nicht geladen werden. Bitte erneut versuchen.')
          setLoading(false)
        }
      }
    }
    load()
    return () => { cancelled = true }
  }, [caseId])

  // ── Render page ───────────────────────────────────────────────────────────

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return
    let cancelled = false

    async function render() {
      // Cancel any in-flight render
      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel() } catch { /* ignore */ }
        renderTaskRef.current = null
      }

      setRendering(true)
      try {
        const page = await pdfDoc.getPage(currentPage)
        if (cancelled) return

        const dpr = window.devicePixelRatio || 1
        // Fit page to container width, apply zoom on top
        const containerWidth = window.innerWidth
        const naturalVp = page.getViewport({ scale: 1 })
        const fitScale = containerWidth / naturalVp.width
        const scale = fitScale * zoom * dpr

        const viewport = page.getViewport({ scale })
        const canvas = canvasRef.current!
        const ctx = canvas.getContext('2d')!

        canvas.width = Math.floor(viewport.width)
        canvas.height = Math.floor(viewport.height)
        canvas.style.width = `${Math.floor(viewport.width / dpr)}px`
        canvas.style.height = `${Math.floor(viewport.height / dpr)}px`

        const task = page.render({ canvasContext: ctx, viewport })
        renderTaskRef.current = task
        await task.promise
        if (!cancelled) setRendering(false)
      } catch (err: any) {
        if (!cancelled && err?.name !== 'RenderingCancelledException') {
          setRendering(false)
        }
      }
    }
    render()
    return () => { cancelled = true }
  }, [pdfDoc, currentPage, zoom])

  // ── Download ──────────────────────────────────────────────────────────────

  const handleDownload = useCallback(() => {
    if (!pdfBytes) return
    const blob = new Blob([pdfBytes.buffer as ArrayBuffer], { type: 'application/pdf' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // Safe filename
    const safeName = title.replace(/[^a-zA-Z0-9\u00C0-\u024F\s-]/g, '').trim() || 'dokument'
    a.download = `${safeName}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }, [pdfBytes, title])

  // ── Double-tap zoom ───────────────────────────────────────────────────────

  const lastTapRef = useRef(0)
  const handleTap = useCallback(() => {
    const now = Date.now()
    if (now - lastTapRef.current < 300) {
      // Double tap: cycle 1× → 2× → 1×
      setZoom(z => (z === 1 ? 2 : 1))
    }
    lastTapRef.current = now
  }, [])

  // ── Swipe navigation ──────────────────────────────────────────────────────

  const touchStartX = useRef<number | null>(null)
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartX.current = e.touches[0].clientX
  }, [])
  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (touchStartX.current === null) return
    const dx = e.changedTouches[0].clientX - touchStartX.current
    touchStartX.current = null
    if (Math.abs(dx) < 50) return // ignore small movements (tap / scroll)
    if (dx < 0) setCurrentPage(p => Math.min(totalPages, p + 1)) // swipe left → next
    if (dx > 0) setCurrentPage(p => Math.max(1, p - 1))           // swipe right → prev
  }, [totalPages])

  // ── Keyboard navigation (desktop/WebView with keyboard) ──────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown')
        setCurrentPage(p => Math.min(totalPages, p + 1))
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp')
        setCurrentPage(p => Math.max(1, p - 1))
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [totalPages, onClose])

  // ── Render ────────────────────────────────────────────────────────────────

  const canGoBack = currentPage > 1
  const canGoNext = currentPage < totalPages

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 300,
        background: 'var(--frya-surface)',
        display: 'flex', flexDirection: 'column',
        fontFamily: "'Plus Jakarta Sans', sans-serif",
      }}
    >
      {/* ── Top bar ──────────────────────────────────────────────────────── */}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: '6px 12px', flexShrink: 0,
          background: 'var(--frya-surface)',
          borderBottom: '1px solid var(--frya-outline-variant)',
        }}
      >
        {/* Back */}
        <button
          onClick={onClose}
          style={iconBtnBase}
          aria-label="Zurück"
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--frya-primary)'; e.currentTarget.style.background = 'var(--frya-surface-container)' }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--frya-on-surface-variant)'; e.currentTarget.style.background = 'transparent' }}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>
            arrow_back
          </span>
        </button>

        {/* Title + page info */}
        <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
          <div style={{
            fontSize: 13, fontWeight: 600, color: 'var(--frya-on-surface)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {title}
          </div>
          {totalPages > 0 && (
            <div style={{ fontSize: 11, color: 'var(--frya-on-surface-variant)' }}>
              Seite {currentPage} von {totalPages}
              {zoom > 1 && ' · ' + zoom + '×'}
            </div>
          )}
        </div>

        {/* Download */}
        <button
          onClick={handleDownload}
          disabled={!pdfBytes}
          style={{ ...iconBtnBase, opacity: pdfBytes ? 1 : 0.4 }}
          aria-label="PDF herunterladen"
          onMouseEnter={e => { if (pdfBytes) { e.currentTarget.style.color = 'var(--frya-primary)'; e.currentTarget.style.background = 'var(--frya-surface-container)' } }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--frya-on-surface-variant)'; e.currentTarget.style.background = 'transparent' }}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 18, fontVariationSettings: "'FILL' 0, 'wght' 300" }}>
            download
          </span>
        </button>
      </div>

      {/* ── PDF canvas area ───────────────────────────────────────────────── */}
      <div
        onClick={handleTap}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        style={{
          flex: 1, overflow: 'auto',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center',
          background: 'var(--frya-surface-container)',
          position: 'relative',
          WebkitOverflowScrolling: 'touch',
        } as React.CSSProperties}
      >
        {loading && <Spinner label="PDF wird geladen…" />}
        {error && <ErrorState message={error} />}

        {!loading && !error && (
          <>
            {/* Dim overlay while re-rendering page */}
            {rendering && (
              <div style={{
                position: 'sticky', top: 0, left: 0, right: 0, height: 3,
                background: 'var(--frya-primary)', zIndex: 1,
                animation: 'frya-slide-in 0.3s ease',
              }} />
            )}
            <canvas
              ref={canvasRef}
              style={{
                display: 'block',
                margin: '12px auto',
                boxShadow: '0 2px 16px rgba(0,0,0,0.2)',
                borderRadius: 4,
                maxWidth: '100%',
              }}
            />
          </>
        )}
      </div>

      {/* ── Bottom navigation (only for multi-page PDFs) ─────────────────── */}
      {totalPages > 1 && (
        <div
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 20,
            padding: '10px 20px', flexShrink: 0,
            borderTop: '1px solid var(--frya-outline-variant)',
            background: 'var(--frya-surface)',
          }}
        >
          <button
            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            disabled={!canGoBack}
            style={{
              ...iconBtnBase,
              opacity: canGoBack ? 1 : 0.3,
              cursor: canGoBack ? 'pointer' : 'default',
            }}
            aria-label="Vorherige Seite"
          >
            <span className="material-symbols-rounded" style={{ fontSize: 24 }}>chevron_left</span>
          </button>

          <span style={{
            fontSize: 13, fontWeight: 600, color: 'var(--frya-on-surface)',
            minWidth: 80, textAlign: 'center',
          }}>
            {currentPage} / {totalPages}
          </span>

          <button
            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            disabled={!canGoNext}
            style={{
              ...iconBtnBase,
              opacity: canGoNext ? 1 : 0.3,
              cursor: canGoNext ? 'pointer' : 'default',
            }}
            aria-label="Nächste Seite"
          >
            <span className="material-symbols-rounded" style={{ fontSize: 24 }}>chevron_right</span>
          </button>
        </div>
      )}

      {/* Spin animation */}
      <style>{`
        @keyframes frya-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes frya-slide-in {
          from { opacity: 0; }
          to { opacity: 1; }
        }
      `}</style>
    </div>
  )
}
