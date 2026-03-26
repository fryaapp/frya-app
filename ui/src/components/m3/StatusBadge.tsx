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
  ANALYZED: { label: 'Analysiert', color: 'bg-info-container text-info' },
  PROPOSED: { label: 'Vorgeschlagen', color: 'bg-warning-container text-warning' },
  APPROVED: { label: 'Freigegeben', color: 'bg-success-container text-success' },
  REJECTED: { label: 'Abgelehnt', color: 'bg-error-container text-error' },
  ARCHIVED: { label: 'Archiviert', color: 'bg-surface-container-high text-on-surface-variant' },
  WAITING_USER: { label: 'Wartet auf dich', color: 'bg-warning-container text-warning' },
  WAITING_DATA: { label: 'Wartet auf Daten', color: 'bg-info-container text-info' },
  SCHEDULED: { label: 'Geplant', color: 'bg-info-container text-info' },
  PENDING_APPROVAL: { label: 'Wartet auf Freigabe', color: 'bg-warning-container text-warning' },
  COMPLETED: { label: 'Erledigt', color: 'bg-success-container text-success' },
}

export function StatusBadge({ status, className = '' }: StatusBadgeProps) {
  const info = statusMap[status] || { label: status, color: 'bg-surface-container-high text-on-surface-variant' }
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-m3-sm text-xs font-semibold ${info.color} ${className}`}>
      {info.label}
    </span>
  )
}
