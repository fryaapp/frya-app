import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { FryaAvatar } from './FryaAvatar'
import { ContentBlock } from '../content/ContentBlock'
import type { UploadProgressData } from '../../stores/fryaStore'

function Timestamp({ ts, visible }: { ts?: number; visible: boolean }) {
  if (!ts) return null
  const d = new Date(ts)
  const time = d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' })
  return (
    <span
      style={{
        fontSize: 10,
        color: 'var(--frya-on-surface-variant)',
        opacity: visible ? 0.5 : 0,
        fontFamily: "'Inter Variable', 'Inter', sans-serif",
        marginTop: 2,
        userSelect: 'none',
        transition: 'opacity 0.15s ease',
        pointerEvents: 'none',
      }}
    >
      {time}
    </span>
  )
}

/**
 * Strip redundant markdown tables / pipe lines from text when content_blocks
 * already visualize the same data. Also strip "FRYA: " prefix.
 */
function cleanText(text: string, blocks?: any[]): string {
  let t = text
  // Remove "FRYA: " prefix
  t = t.replace(/^FRYA:\s*/i, '')
  // If content_blocks exist, remove markdown table lines (pipe-separated rows)
  if (blocks && blocks.length > 0) {
    t = t
      .split('\n')
      .filter((line) => {
        const trimmed = line.trim()
        // Remove lines that look like markdown table rows: | xxx | xxx |
        if (trimmed.startsWith('|') && trimmed.endsWith('|')) return false
        // Remove separator lines: |---|---|
        if (/^\|[-\s|:]+\|$/.test(trimmed)) return false
        return true
      })
      .join('\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
  }
  return t
}

const STAGE_LABELS: Record<string, string> = {
  uploading: 'Wird hochgeladen...',
  ocr: 'OCR liest den Beleg...',
  analysis: 'Analysiere Inhalt...',
  booking: 'Erstelle Buchungsvorschlag...',
  done: 'Fertig',
}

function UploadProgressCard({ data }: { data: UploadProgressData }) {
  const isDone = data.stage === 'done'
  // percent=0 on done means error/cancelled — hide the card
  if (isDone && data.percent === 0) return null

  const label = STAGE_LABELS[data.stage] ?? data.stage
  const percent = isDone ? 100 : data.percent
  const barColor = isDone ? 'var(--frya-primary)' : 'var(--frya-primary)'
  const trackColor = 'var(--frya-surface-container-high)'

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        marginBottom: 12,
        animation: 'frya-fade-up 300ms ease both',
      }}
    >
      <FryaAvatar size={22} style={{ marginTop: 2 }} />
      <div
        style={{
          background: 'var(--frya-surface-container-low)',
          border: '1px solid var(--frya-outline-variant)',
          borderRadius: 12,
          padding: '12px 14px',
          minWidth: 220,
          maxWidth: 320,
        }}
      >
        {/* Filename */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 8,
          }}
        >
          <span
            className="material-symbols-rounded"
            style={{
              fontSize: 16,
              color: 'var(--frya-primary)',
              fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 16",
            }}
          >
            {isDone ? 'check_circle' : 'description'}
          </span>
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--frya-on-surface)',
              fontFamily: "'Inter Variable', 'Inter', sans-serif",
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 220,
            }}
            title={data.filename}
          >
            {data.filename}
          </span>
        </div>

        {/* Progress bar */}
        <div
          style={{
            height: 6,
            borderRadius: 3,
            background: trackColor,
            overflow: 'hidden',
            marginBottom: 6,
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${percent}%`,
              background: barColor,
              borderRadius: 3,
              transition: 'width 600ms ease',
            }}
          />
        </div>

        {/* Stage label */}
        <div
          style={{
            fontSize: 11,
            color: 'var(--frya-on-surface-variant)',
            fontFamily: "'Inter Variable', 'Inter', sans-serif",
          }}
        >
          {isDone ? `${label} \u2713` : label}
        </div>
      </div>
    </div>
  )
}

interface ChatMessageData {
  id: string
  role: 'user' | 'frya' | 'assistant' | 'system'
  text: string
  content_blocks?: Array<{ block_type: string; data: any }>
  actions?: Array<{ label: string; action: string; icon?: string; variant?: string }>
  timestamp?: number
  uploadProgress?: UploadProgressData
}

interface ChatMessageProps {
  message: ChatMessageData
  onAction?: (action: any) => void
  onSubmit?: (formType: string, formData: Record<string, any>) => void
}

export function ChatMessage({ message, onAction, onSubmit }: ChatMessageProps) {
  const isUser = message.role === 'user'

  const [hovered, setHovered] = useState(false)

  // Upload progress card
  if (message.uploadProgress) {
    return <UploadProgressCard data={message.uploadProgress} />
  }

  if (isUser) {
    return (
      <div
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-end',
          marginBottom: 12,
          animation: 'frya-fade-up 300ms ease both',
        }}
      >
        <div
          style={{
            maxWidth: '75%',
            background: 'var(--frya-primary-container)',
            color: 'var(--frya-on-primary-container)',
            borderRadius: '18px 18px 4px 18px',
            padding: '11px 16px',
            fontSize: 15,
            lineHeight: 1.6,
            fontFamily: "'Inter Variable', 'Inter', sans-serif",
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {message.text}
        </div>
        <Timestamp ts={message.timestamp} visible={hovered} />
      </div>
    )
  }

  // Frya (assistant) message
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        marginBottom: 12,
        animation: 'frya-fade-up 300ms ease both',
      }}
    >
      <FryaAvatar size={22} style={{ marginTop: 2 }} />

      <div style={{ flex: 1, minWidth: 0, maxWidth: '75%' }}>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--frya-on-surface-variant)',
            fontFamily: "'Inter Variable', 'Inter', sans-serif",
            display: 'block',
            marginBottom: 4,
          }}
        >
          Frya
        </span>

        <div
          style={{
            fontSize: 15,
            lineHeight: 1.65,
            color: 'var(--frya-on-surface)',
            fontFamily: "'Inter Variable', 'Inter', sans-serif",
          }}
        >
          <ReactMarkdown
            remarkPlugins={[]}
            components={{
              // Hide raw markdown tables when content_blocks render the same data
              table: () => null,
              thead: () => null,
              tbody: () => null,
              p: ({ children }) => (
                <p style={{ marginBottom: 6 }}>{children}</p>
              ),
              strong: ({ children }) => (
                <strong style={{ fontWeight: 600 }}>{children}</strong>
              ),
              ul: ({ children }) => (
                <ul style={{ listStyle: 'disc', paddingLeft: 16, marginBottom: 6 }}>{children}</ul>
              ),
              ol: ({ children }) => (
                <ol style={{ listStyle: 'decimal', paddingLeft: 16, marginBottom: 6 }}>{children}</ol>
              ),
              a: ({ href, children }) => (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--frya-primary)', textDecoration: 'underline' }}
                >
                  {children}
                </a>
              ),
              code: ({ className, children, ...props }) => {
                const isBlock = className?.includes('language-')
                return isBlock ? (
                  <code
                    style={{
                      display: 'block',
                      background: 'var(--frya-surface-container)',
                      padding: '8px 12px',
                      borderRadius: 8,
                      fontSize: 12,
                      fontFamily: 'monospace',
                      margin: '6px 0',
                      overflowX: 'auto',
                      whiteSpace: 'pre',
                    }}
                    {...props}
                  >
                    {children}
                  </code>
                ) : (
                  <code
                    style={{
                      background: 'var(--frya-surface-container)',
                      padding: '1px 4px',
                      borderRadius: 4,
                      fontSize: 12,
                      fontFamily: 'monospace',
                    }}
                    {...props}
                  >
                    {children}
                  </code>
                )
              },
            }}
          >
            {cleanText(message.text || '', message.content_blocks)}
          </ReactMarkdown>
        </div>

        {/* Content blocks */}
        {message.content_blocks && message.content_blocks.length > 0 && (
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {message.content_blocks.map((block, i) => (
              <ContentBlock key={i} block={block} onAction={onAction} onSubmit={onSubmit} />
            ))}
          </div>
        )}

        {/* Timestamp on hover */}
        <Timestamp ts={message.timestamp} visible={hovered} />

        {/* Action buttons */}
        {message.actions && message.actions.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
            {message.actions.map((act, i) => (
              <button
                key={i}
                onClick={() => onAction?.(act)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 14px',
                  fontSize: 12,
                  fontWeight: 500,
                  fontFamily: "'Inter Variable', 'Inter', sans-serif",
                  borderRadius: 18,
                  border: act.variant === 'filled'
                    ? 'none'
                    : '1px solid var(--frya-outline-variant)',
                  background: act.variant === 'filled'
                    ? 'var(--frya-primary)'
                    : 'transparent',
                  color: act.variant === 'filled'
                    ? 'var(--frya-on-primary)'
                    : 'var(--frya-on-surface)',
                  cursor: 'pointer',
                  transition: 'background 150ms, border-color 150ms',
                }}
                onMouseEnter={(e) => {
                  if (act.variant !== 'filled') {
                    e.currentTarget.style.background = 'var(--frya-surface-container-high)'
                    e.currentTarget.style.borderColor = 'var(--frya-primary)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (act.variant !== 'filled') {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.borderColor = 'var(--frya-outline-variant)'
                  }
                }}
              >
                {act.icon && (
                  <span
                    className="material-symbols-rounded"
                    style={{
                      fontSize: 16,
                      fontVariationSettings: "'FILL' 0, 'wght' 400, 'GRAD' 0, 'opsz' 16",
                    }}
                  >
                    {act.icon}
                  </span>
                )}
                {act.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
