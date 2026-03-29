import { type ReactNode, useState, useCallback, useRef, useEffect } from 'react'
import { useUiStore } from '../../stores/uiStore'

interface SplitViewProps {
  contextContent: ReactNode
  chatContent: ReactNode
  idleContent: ReactNode
}

/**
 * SplitView — Core layout.
 * Idle: fullscreen greeting. Active: draggable split (context top, chat bottom).
 * Mobile: larger context area (70%) so content isn't hidden behind chat.
 * Desktop: balanced 58/42 split.
 */
export function SplitView({ contextContent, chatContent, idleContent }: SplitViewProps) {
  const splitOpen = useUiStore((s) => s.splitOpen)
  const contextType = useUiStore((s) => s.contextType)
  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768
  const [splitPct, setSplitPct] = useState(isMobile ? 72 : 58)

  // Adjust on resize
  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768
      setSplitPct((prev) => {
        // Only reset if user hasn't manually dragged
        if (prev === 72 || prev === 58) return mobile ? 72 : 58
        return prev
      })
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    dragging.current = true
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
  }, [])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const pct = ((e.clientY - rect.top) / rect.height) * 100
    setSplitPct(Math.min(80, Math.max(25, pct)))
  }, [])

  const handlePointerUp = useCallback(() => {
    dragging.current = false
  }, [])

  return (
    <div className="relative h-full overflow-hidden">
      {/* IDLE STATE */}
      <div
        className="absolute inset-0 transition-all duration-500"
        style={{
          transitionTimingFunction: 'cubic-bezier(.4,0,.2,1)',
          opacity: splitOpen ? 0 : 1,
          pointerEvents: splitOpen ? 'none' : 'auto',
          transform: splitOpen ? 'translateY(-20px)' : 'translateY(0)',
        }}
      >
        {idleContent}
      </div>

      {/* SPLIT STATE */}
      <div
        ref={containerRef}
        className="absolute inset-0 flex flex-col transition-all duration-500"
        style={{
          transitionTimingFunction: 'cubic-bezier(.4,0,.2,1)',
          opacity: splitOpen ? 1 : 0,
          pointerEvents: splitOpen ? 'auto' : 'none',
          transform: splitOpen ? 'translateY(0)' : 'translateY(20px)',
        }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        {/* Context Panel */}
        <div className="relative min-h-0" style={{ flex: `0 0 ${splitPct}%` }}>
          <div className="h-full overflow-y-auto">
            {contextType !== 'none' ? contextContent : (
              <div className="flex items-center justify-center h-full" />
            )}
          </div>
        </div>

        {/* Drag Handle / Separator */}
        <div
          className="shrink-0 flex items-center justify-center cursor-row-resize group"
          style={{ height: '20px', touchAction: 'none' }}
          onPointerDown={handlePointerDown}
        >
          {/* Thin line full width */}
          <div
            className="absolute left-0 right-0"
            style={{ height: '1px', background: 'var(--frya-outline-variant)', opacity: 0.3 }}
          />
          {/* Drag pill in center — more visible */}
          <div
            className="relative z-10 transition-all group-hover:scale-x-125"
            style={{
              width: '40px',
              height: '5px',
              borderRadius: '3px',
              background: 'var(--frya-primary)',
              opacity: 0.5,
            }}
          />
        </div>

        {/* Chat Panel */}
        <div
          className="min-h-0 flex-1 bg-surface-container-lowest"
          style={{ borderTopLeftRadius: '20px', borderTopRightRadius: '20px' }}
        >
          {chatContent}
        </div>
      </div>
    </div>
  )
}
