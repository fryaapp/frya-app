import { Icon } from '../m3'

interface NotificationBubbleProps {
  text: string
  notificationType: string
}

const typeConfig: Record<string, { icon: string; color: string }> = {
  analysis: { icon: 'analytics', color: 'text-info' },
  success: { icon: 'check_circle', color: 'text-success' },
  warning: { icon: 'warning', color: 'text-warning' },
  error: { icon: 'error', color: 'text-error' },
  document_processed: { icon: 'description', color: 'text-success' },
}

export function NotificationBubble({ text, notificationType }: NotificationBubbleProps) {
  const cfg = typeConfig[notificationType] || typeConfig.analysis

  return (
    <div className="flex justify-center mb-3">
      <div className="inline-flex items-center gap-2 px-4 py-2 bg-surface-container rounded-m3-xl">
        <Icon name={cfg.icon} size={16} className={cfg.color} />
        <span className="text-xs text-on-surface-variant">{text}</span>
      </div>
    </div>
  )
}
