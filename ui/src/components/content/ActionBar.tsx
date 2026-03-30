import React from 'react'

interface ActionItem {
  label: string
  chat_text?: string
  style?: 'primary' | 'secondary' | 'text'
  quick_action?: boolean
}

interface ActionBarProps {
  actions: ActionItem[]
  onAction: (action: ActionItem) => void
}

export function ActionBar({ actions, onAction }: ActionBarProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 5,
      }}
    >
      {(actions || []).map((action, i) => (
        <ActionButton key={i} action={action} onClick={() => onAction(action)} />
      ))}
    </div>
  )
}

function ActionButton({
  action,
  onClick,
}: {
  action: ActionItem
  onClick: () => void
}) {
  const [hovered, setHovered] = React.useState(false)

  const variant = action.style || 'secondary'

  const baseStyle: React.CSSProperties = {
    borderRadius: 18,
    fontSize: 11,
    fontWeight: 500,
    fontFamily: 'Plus Jakarta Sans, sans-serif',
    padding: '6px 13px',
    cursor: 'pointer',
    transition: 'opacity 0.15s ease, background 0.15s ease',
    opacity: hovered ? 0.85 : 1,
    whiteSpace: 'nowrap',
  }

  const variants: Record<string, React.CSSProperties> = {
    primary: {
      ...baseStyle,
      background: 'var(--frya-primary)',
      color: 'var(--frya-on-primary)',
      border: 'none',
      fontWeight: 600,
    },
    secondary: {
      ...baseStyle,
      background: 'transparent',
      color: 'var(--frya-on-surface)',
      border: '1px solid var(--frya-outline-variant)',
    },
    text: {
      ...baseStyle,
      background: 'transparent',
      color: 'var(--frya-on-surface-variant)',
      border: 'none',
      padding: '6px 8px',
    },
  }

  return (
    <button
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={onClick}
      style={variants[variant] || variants.secondary}
    >
      {action.label}
    </button>
  )
}
