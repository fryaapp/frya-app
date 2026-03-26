interface ChipProps {
  label: string
  color?: 'primary' | 'success' | 'warning' | 'error' | 'info' | 'default'
  icon?: string
  onClick?: () => void
  className?: string
}

const chipColors: Record<string, string> = {
  primary: 'bg-primary-container text-on-primary-container',
  success: 'bg-success-container text-success',
  warning: 'bg-warning-container text-warning',
  error: 'bg-error-container text-error',
  info: 'bg-info-container text-info',
  default: 'border border-outline-variant text-on-surface hover:bg-surface-container-high',
}

export function Chip({ label, color = 'default', icon, onClick, className = '' }: ChipProps) {
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag
      className={`inline-flex items-center gap-1 px-3.5 py-1.5 rounded-[20px] text-xs font-medium transition-all ${chipColors[color]} ${onClick ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
    >
      {icon && <span className="material-symbols-rounded" style={{ fontSize: 16 }}>{icon}</span>}
      {label}
    </Tag>
  )
}
