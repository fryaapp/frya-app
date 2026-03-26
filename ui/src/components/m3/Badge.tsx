interface BadgeProps {
  confidence: number | null
  className?: string
}

function getConfidenceInfo(c: number | null): { label: string; color: string } {
  if (c === null) return { label: 'Unbekannt', color: 'bg-surface-container-high text-on-surface-variant' }
  if (c >= 0.85) return { label: 'Sicher', color: 'bg-success-container text-success' }
  if (c >= 0.65) return { label: 'Hoch', color: 'bg-info-container text-info' }
  if (c >= 0.40) return { label: 'Mittel', color: 'bg-warning-container text-warning' }
  return { label: 'Unsicher', color: 'bg-error-container text-error border border-dashed border-error/30' }
}

export function ConfidenceBadge({ confidence, className = '' }: BadgeProps) {
  const { label, color } = getConfidenceInfo(confidence)
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-m3-sm text-xs font-semibold ${color} ${className}`}>
      {label}
    </span>
  )
}
