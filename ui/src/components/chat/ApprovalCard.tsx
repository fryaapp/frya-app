import { useState } from 'react'
import type { ApprovalData } from '../../stores/chatStore'
import { Button, Icon } from '../m3'
import { api } from '../../lib/api'

interface ApprovalCardProps {
  data: ApprovalData
  messageId: string
  resolvedAction?: string
  onResolved: (messageId: string, action: string) => void
}

const actionLabels: Record<string, { label: string; variant: 'filled' | 'tonal' | 'outlined' | 'text'; icon: string }> = {
  approve: { label: 'Freigeben', variant: 'filled', icon: 'check' },
  correct: { label: 'Korrigieren', variant: 'tonal', icon: 'edit' },
  reject: { label: 'Ablehnen', variant: 'outlined', icon: 'close' },
  defer: { label: 'Später', variant: 'text', icon: 'schedule' },
}

const resolvedLabels: Record<string, string> = {
  approve: 'Freigegeben',
  correct: 'Wird korrigiert',
  reject: 'Abgelehnt',
  defer: 'Zurückgestellt',
}

export function ApprovalCard({ data, messageId, resolvedAction, onResolved }: ApprovalCardProps) {
  const [loading, setLoading] = useState(false)

  const handleAction = async (action: string) => {
    setLoading(true)
    try {
      await api.post(`/inbox/${data.case_id}/approve`, { action })
      onResolved(messageId, action)
    } catch {
      setLoading(false)
    }
  }

  const currency = data.currency || 'EUR'
  const amount = new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(data.amount)

  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[90%] bg-surface-container-high rounded-m3-lg p-4 space-y-3">
        {/* Header */}
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-m3-sm bg-primary-container flex items-center justify-center shrink-0">
            <Icon name="receipt_long" size={20} className="text-on-primary-container" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-on-surface truncate">{data.vendor}</p>
            {data.document_type && (
              <p className="text-xs text-on-surface-variant">{data.document_type}</p>
            )}
            {data.case_number && (
              <p className="text-xs text-on-surface-variant/60">{data.case_number}</p>
            )}
          </div>
          <p className="text-lg font-display font-bold text-on-surface ml-auto whitespace-nowrap">{amount}</p>
        </div>

        {/* KI-Label (EU AI Act) */}
        <p className="text-xs text-on-surface-variant/70 flex items-center gap-1">
          <Icon name="smart_toy" size={14} />
          KI-Vorschlag &middot; bitte pr&uuml;fen
        </p>

        {/* Buttons or resolved state */}
        {resolvedAction ? (
          <div className="flex items-center gap-2 py-1">
            <Icon name="check_circle" size={18} className="text-success" />
            <span className="text-sm text-on-surface-variant">{resolvedLabels[resolvedAction] || resolvedAction}</span>
          </div>
        ) : (
          <div className="flex flex-wrap gap-2">
            {data.buttons
              .filter((b) => b !== 'payment_execute') // NIEMALS payment_execute Button
              .map((action) => {
                const cfg = actionLabels[action] || { label: action, variant: 'text' as const, icon: 'help' }
                return (
                  <Button
                    key={action}
                    variant={cfg.variant}
                    icon={cfg.icon}
                    onClick={() => handleAction(action)}
                    disabled={loading}
                    className="text-xs px-4 py-1.5 min-h-[36px]"
                  >
                    {cfg.label}
                  </Button>
                )
              })}
          </div>
        )}
      </div>
    </div>
  )
}
