import { Icon } from '../m3'

interface TopBarProps {
  title?: string
  showBack?: boolean
  onBack?: () => void
  actions?: React.ReactNode
}

export function TopBar({ title, showBack, onBack, actions }: TopBarProps) {
  return (
    <header className="sticky top-0 z-40 bg-surface/95 backdrop-blur-sm border-b border-outline-variant/50">
      <div className="flex items-center h-14 px-4 max-w-3xl mx-auto">
        {showBack && (
          <button onClick={onBack} className="mr-2 p-2 -ml-2 rounded-full hover:bg-surface-container-high min-h-[48px] min-w-[48px] flex items-center justify-center">
            <Icon name="arrow_back" />
          </button>
        )}
        {title && (
          <h1 className="text-lg font-display font-semibold text-on-surface flex-1 truncate">
            {title}
          </h1>
        )}
        {actions && <div className="flex items-center gap-1">{actions}</div>}
      </div>
    </header>
  )
}
