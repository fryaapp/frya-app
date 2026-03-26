import type { ReactNode } from 'react'
import { useUiStore } from '../../stores/uiStore'
import { Icon } from '../m3'

interface SplitViewProps {
  /** Content for the context panel (top ~58%) */
  contextContent: ReactNode
  /** Content for the chat panel (bottom ~42%) */
  chatContent: ReactNode
  /** Content shown when split is closed (idle state) */
  idleContent: ReactNode
}

/**
 * SplitView — The core layout component.
 *
 * Idle: shows idleContent fullscreen (Frya greeting)
 * Active: smooth animation splits into top (context) + bottom (chat)
 * Transition: 500ms cubic-bezier(.4,0,.2,1)
 *
 * NO visible slider, NO drag handle. Only a subtle separator line.
 */
export function SplitView({ contextContent, chatContent, idleContent }: SplitViewProps) {
  const splitOpen = useUiStore((s) => s.splitOpen)
  const contextType = useUiStore((s) => s.contextType)
  const closeSplit = useUiStore((s) => s.closeSplit)

  return (
    <div className="relative h-full overflow-hidden">
      {/* IDLE STATE — fullscreen when split is closed */}
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

      {/* SPLIT STATE — context top + chat bottom */}
      <div
        className="absolute inset-0 flex flex-col transition-all duration-500"
        style={{
          transitionTimingFunction: 'cubic-bezier(.4,0,.2,1)',
          opacity: splitOpen ? 1 : 0,
          pointerEvents: splitOpen ? 'auto' : 'none',
          transform: splitOpen ? 'translateY(0)' : 'translateY(20px)',
        }}
      >
        {/* Context Panel — top ~58% */}
        <div className="relative" style={{ flex: '0 0 58%', maxHeight: '58%' }}>
          {/* Close button */}
          <button
            onClick={closeSplit}
            className="absolute top-2 right-2 z-10 w-8 h-8 flex items-center justify-center rounded-full bg-surface-container-high/80 hover:bg-surface-container-highest transition-colors"
            aria-label="Kontext schließen"
          >
            <Icon name="close" size={18} className="text-on-surface-variant" />
          </button>

          <div className="h-full overflow-y-auto">
            {contextType !== 'none' ? contextContent : (
              <div className="flex items-center justify-center h-full text-on-surface-variant/40 text-sm">
                Kontext wird geladen...
              </div>
            )}
          </div>
        </div>

        {/* Subtle separator — NO slider, NO drag handle */}
        <div className="h-px bg-outline-variant/40 shrink-0" />

        {/* Chat Panel — bottom ~42% */}
        <div style={{ flex: '0 0 42%', maxHeight: '42%' }} className="min-h-0">
          {chatContent}
        </div>
      </div>
    </div>
  )
}
