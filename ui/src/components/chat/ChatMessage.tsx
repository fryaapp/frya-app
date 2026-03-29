import ReactMarkdown from 'react-markdown'
import { FryaAvatar } from './FryaAvatar'
import { ContentBlock } from '../content/ContentBlock'

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

interface ChatMessageData {
  id: string
  role: 'user' | 'frya' | 'assistant' | 'system'
  text: string
  content_blocks?: Array<{ block_type: string; data: any }>
  actions?: Array<{ label: string; action: string; icon?: string; variant?: string }>
  timestamp?: number
}

interface ChatMessageProps {
  message: ChatMessageData
  onAction?: (action: any) => void
  onSubmit?: (formType: string, formData: Record<string, any>) => void
}

export function ChatMessage({ message, onAction, onSubmit }: ChatMessageProps) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'flex-end',
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
            padding: '10px 16px',
            fontSize: 13,
            lineHeight: 1.55,
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {message.text}
        </div>
      </div>
    )
  }

  // Frya (assistant) message
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

      <div style={{ flex: 1, minWidth: 0, maxWidth: '75%' }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--frya-on-surface-variant)',
            fontFamily: "'Plus Jakarta Sans', sans-serif",
            display: 'block',
            marginBottom: 4,
          }}
        >
          Frya
        </span>

        <div
          style={{
            fontSize: 13,
            lineHeight: 1.65,
            color: 'var(--frya-on-surface)',
            fontFamily: "'Plus Jakarta Sans', sans-serif",
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
                  fontFamily: "'Plus Jakarta Sans', sans-serif",
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
