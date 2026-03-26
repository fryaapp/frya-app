import { useState } from 'react'
import { Button, Chip, Icon } from '../m3'
import { api } from '../../lib/api'

interface ApprovalButtonsProps {
  caseId: string
  onAction: (action: string) => void
}

type Phase = 'buttons' | 'correction_reason' | 'learn_scope' | 'done'
type LearnScope = 'this_only' | 'vendor_always' | 'category_always' | 'ask_every_time'

const correctionReasons = [
  { label: 'Privat statt betrieblich', value: 'private_not_business' },
  { label: 'Anderes Konto', value: 'wrong_account' },
  { label: 'Betrag falsch', value: 'wrong_amount' },
]

const learnScopes: Array<{ label: string; value: LearnScope; icon: string }> = [
  { label: 'Nur dieser eine', value: 'this_only', icon: 'looks_one' },
  { label: 'Absender immer so', value: 'vendor_always', icon: 'storefront' },
  { label: 'Typ immer so', value: 'category_always', icon: 'category' },
  { label: 'Frag mich', value: 'ask_every_time', icon: 'help' },
]

const resolvedLabels: Record<string, string> = {
  approve: 'Freigegeben',
  correct: 'Korrektur gespeichert',
  reject: 'Abgelehnt',
  defer: 'Zurückgestellt',
}

export function ApprovalButtons({ caseId, onAction }: ApprovalButtonsProps) {
  const [phase, setPhase] = useState<Phase>('buttons')
  const [loading, setLoading] = useState(false)
  const [resolvedAction, setResolvedAction] = useState<string | null>(null)
  const [selectedReason, setSelectedReason] = useState<string | null>(null)
  const [selectedScope, setSelectedScope] = useState<LearnScope | null>(null)

  const handleAction = async (action: string) => {
    if (action === 'correct') {
      setPhase('correction_reason')
      return
    }

    setLoading(true)
    try {
      await api.post(`/inbox/${caseId}/approve`, { action })
      setResolvedAction(action)
      setPhase('done')
      onAction(action)
    } catch {
      setLoading(false)
    }
  }

  const handleReasonSelected = (reason: string) => {
    setSelectedReason(reason)
    setPhase('learn_scope')
  }

  const handleLearnScope = async (scope: LearnScope) => {
    setSelectedScope(scope)
    setLoading(true)
    try {
      await api.post(`/inbox/${caseId}/approve`, { action: 'correct', correction_reason: selectedReason })
      await api.post(`/inbox/${caseId}/learn`, { scope })
      setResolvedAction('correct')
      setPhase('done')
      onAction('correct')
    } catch {
      setLoading(false)
    }
  }

  /* Bereits erledigt */
  if (phase === 'done' && resolvedAction) {
    return (
      <div className="flex items-center gap-2 py-2 px-4">
        <Icon name="check_circle" size={18} className="text-success" />
        <span className="text-sm text-on-surface-variant">{resolvedLabels[resolvedAction] ?? resolvedAction}</span>
      </div>
    )
  }

  /* Korrektur-Grund auswählen */
  if (phase === 'correction_reason') {
    return (
      <div className="px-4 py-3 space-y-3">
        <p className="text-xs font-semibold text-on-surface-variant">Was stimmt nicht?</p>
        <div className="flex flex-wrap gap-2">
          {correctionReasons.map((r) => (
            <Chip
              key={r.value}
              label={r.label}
              color="warning"
              icon="edit"
              onClick={() => handleReasonSelected(r.value)}
            />
          ))}
        </div>
        <button
          onClick={() => setPhase('buttons')}
          className="text-xs text-on-surface-variant underline"
        >
          Abbrechen
        </button>
      </div>
    )
  }

  /* Lern-Scope auswählen */
  if (phase === 'learn_scope') {
    return (
      <div className="px-4 py-3 space-y-3">
        <p className="text-xs font-semibold text-on-surface-variant">Wie soll FRYA lernen?</p>
        <div className="flex flex-wrap gap-2">
          {learnScopes.map((s) => (
            <Chip
              key={s.value}
              label={s.label}
              color={selectedScope === s.value ? 'primary' : 'default'}
              icon={s.icon}
              onClick={() => handleLearnScope(s.value)}
            />
          ))}
        </div>

        {/* Warnung bei globalen Lerneffekten */}
        {selectedScope && (selectedScope === 'vendor_always' || selectedScope === 'category_always') && (
          <div className="flex items-start gap-2 p-2 rounded-m3-sm bg-warning-container/30">
            <Icon name="warning" size={16} className="text-warning shrink-0 mt-0.5" />
            <p className="text-xs text-on-surface-variant">
              Achtung: Dieser Lerneffekt gilt f&uuml;r alle zuk&uuml;nftigen Belege dieses Typs.
            </p>
          </div>
        )}

        {loading && (
          <div className="flex items-center gap-2">
            <Icon name="hourglass_empty" size={16} className="text-on-surface-variant animate-pulse" />
            <span className="text-xs text-on-surface-variant">Wird gespeichert...</span>
          </div>
        )}

        <button
          onClick={() => { setPhase('correction_reason'); setSelectedScope(null) }}
          className="text-xs text-on-surface-variant underline"
          disabled={loading}
        >
          Zur&uuml;ck
        </button>
      </div>
    )
  }

  /* Haupt-Buttons */
  return (
    <div className="flex flex-wrap gap-2 px-4 py-3">
      <Button variant="filled" icon="check" onClick={() => handleAction('approve')} disabled={loading}>
        Freigeben
      </Button>
      <Button variant="tonal" icon="edit" onClick={() => handleAction('correct')} disabled={loading}>
        Korrigieren
      </Button>
      <Button variant="outlined" icon="close" onClick={() => handleAction('reject')} disabled={loading}>
        Ablehnen
      </Button>
      <Button variant="text" icon="schedule" onClick={() => handleAction('defer')} disabled={loading}>
        Sp&auml;ter
      </Button>
    </div>
  )
}
