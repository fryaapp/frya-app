type CardVariant = 'elevated' | 'filled' | 'outlined'

interface CardProps {
  variant?: CardVariant
  className?: string
  children: React.ReactNode
  onClick?: () => void
}

const cardVariants: Record<CardVariant, string> = {
  elevated: 'bg-surface-container-low rounded-[14px]',
  filled: 'bg-surface-container-low rounded-[14px]',
  outlined: 'border border-outline-variant rounded-[14px] bg-transparent',
}

export function Card({ variant = 'filled', className = '', children, onClick }: CardProps) {
  return (
    <div
      className={`px-[14px] py-3 ${cardVariants[variant]} ${onClick ? 'cursor-pointer hover:bg-surface-container-high transition-colors' : ''} ${className}`}
      onClick={onClick}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } } : undefined}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      {children}
    </div>
  )
}
