import { Icon } from './Icon'

type ButtonVariant = 'filled' | 'tonal' | 'outlined' | 'text'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  icon?: string
  children: React.ReactNode
}

const variants: Record<ButtonVariant, string> = {
  filled: 'bg-primary text-on-primary hover:opacity-90',
  tonal: 'bg-secondary-container text-on-secondary-container hover:opacity-90',
  outlined: 'border border-outline text-primary hover:bg-primary/8',
  text: 'text-primary hover:bg-primary/8',
}

export function Button({ variant = 'filled', icon, children, className = '', ...props }: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 px-6 py-2.5 rounded-m3-xl font-semibold text-sm transition-all min-h-[48px] disabled:opacity-40 ${variants[variant]} ${className}`}
      {...props}
    >
      {icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  )
}
