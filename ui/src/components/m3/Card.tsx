type CardVariant = 'elevated' | 'filled' | 'outlined'

interface CardProps {
  variant?: CardVariant
  className?: string
  children: React.ReactNode
  onClick?: () => void
}

const cardVariants: Record<CardVariant, string> = {
  elevated: 'bg-surface-container-low shadow-sm',
  filled: 'bg-surface-container',
  outlined: 'bg-surface border border-outline-variant',
}

export function Card({ variant = 'filled', className = '', children, onClick }: CardProps) {
  return (
    <div
      className={`rounded-m3 p-4 ${cardVariants[variant]} ${onClick ? 'cursor-pointer hover:opacity-90 transition-opacity' : ''} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  )
}
