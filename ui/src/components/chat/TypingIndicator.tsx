import { FryaAvatar } from './FryaAvatar'

interface TypingIndicatorProps {
  hint?: string | null
}

const dotStyle = (delay: number): React.CSSProperties => ({
  width: 6,
  height: 6,
  borderRadius: '50%',
  background: 'var(--frya-on-surface-variant)',
  animation: `frya-dot-bounce 600ms ease-in-out ${delay}ms infinite`,
})

export function TypingIndicator({ hint }: TypingIndicatorProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-end',
        gap: 8,
        marginBottom: 12,
        animation: 'frya-fade-up 300ms ease both',
      }}
    >
      <FryaAvatar size={22} spinning />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--frya-on-surface-variant)',
            fontFamily: "'Plus Jakarta Sans', sans-serif",
          }}
        >
          Frya
        </span>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            background: 'var(--frya-surface-container)',
            borderRadius: '18px 18px 18px 4px',
            padding: '10px 14px',
          }}
        >
          <div style={dotStyle(0)} />
          <div style={dotStyle(100)} />
          <div style={dotStyle(200)} />
        </div>

        {hint && (
          <span
            style={{
              fontSize: 11,
              color: 'var(--frya-on-surface-variant)',
              fontStyle: 'italic',
              fontFamily: "'Plus Jakarta Sans', sans-serif",
              paddingLeft: 4,
            }}
          >
            {hint}
          </span>
        )}
      </div>

      <style>{`
        @keyframes frya-dot-bounce {
          0%, 100% { transform: translateY(0); opacity: 0.5; }
          50% { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  )
}
