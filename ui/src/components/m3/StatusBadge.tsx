interface StatusBadgeProps {
  status: string
  className?: string
}

const statusMap: Record<string, { label: string; color: string }> = {
  DRAFT: { label: 'Entwurf', color: 'bg-surface-container-high text-on-surface-variant' },
  OPEN: { label: 'Offen', color: 'bg-info-container text-info' },
  OVERDUE: { label: 'Überfällig', color: 'bg-error-container text-error' },
  BOOKED: { label: 'Gebucht', color: 'bg-success-container text-success' },
  PAID: { label: 'Bezahlt', color: 'bg-success-container text-success' },
  CLOSED: { label: 'Abgeschlossen', color: 'bg-surface-container-high text-on-surface-variant' },
  CANCELLED: { label: 'Storniert', color: 'bg-error-container text-error line-through' },
  PARTIALLY_PAID: { label: 'Teilweise bezahlt', color: 'bg-warning-container text-warning' },
  SENT: { label: 'Versendet', color: 'bg-info-container text-info' },
}

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const info = statusMap[status] || { label: status, color: 'bg-surface-container-high text-on-surface-variant' }
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-m3-sm text-xs font-semibold ${info.color} ${className}`}>
      {info.label}
    </span>
  )
}
