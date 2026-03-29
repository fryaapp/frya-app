/**
 * Shared FRYA avatar component.
 * Uses the actual FRYA character image instead of a generic icon.
 * Used in ChatMessage, TypingIndicator, GreetingScreen.
 */

interface FryaAvatarProps {
  size?: number
  spinning?: boolean
  className?: string
  style?: React.CSSProperties
}

export function FryaAvatar({ size = 22, spinning = false, className = '', style }: FryaAvatarProps) {
  return (
    <div
      className={className}
      style={{
        width: size,
        height: size,
        minWidth: size,
        minHeight: size,
        borderRadius: '50%',
        overflow: 'hidden',
        flexShrink: 0,
        background: 'var(--frya-primary-container)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        animation: spinning ? 'frya-avatar-pulse 1.4s ease-in-out infinite' : undefined,
        ...style,
      }}
    >
      <img
        src="/frya-avatar.png"
        alt="Frya"
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          borderRadius: '50%',
        }}
      />
    </div>
  )
}
