import { useState } from 'react'
import { Card, Button, Input, Chip, Icon } from '../m3'
import { api } from '../../lib/api'

interface CorrectionDialogProps {
  caseId: string
  currentProposal: {
    skr03_soll: string
    skr03_soll_name: string
    skr03_haben: string
    skr03_haben_name: string
  } | null
  onDone: () => void
  onCancel: () => void
}

type LearnScope = 'this_only' | 'vendor_always' | 'category_always' | 'ask_every_time'

const SCOPE_OPTIONS: { value: LearnScope; label: string }[] = [
  { value: 'this_only', label: 'Nur diesmal' },
  { value: 'vendor_always', label: 'Immer für Lieferant' },
  { value: 'category_always', label: 'Immer für Kategorie' },
  { value: 'ask_every_time', label: 'Immer nachfragen' },
]

export function CorrectionDialog({ caseId, currentProposal, onDone, onCancel }: CorrectionDialogProps) {
  const [kontoSoll, setKontoSoll] = useState(currentProposal?.skr03_soll ?? '')
  const [kontoHaben, setKontoHaben] = useState(currentProposal?.skr03_haben ?? '')
  const [betrag, setBetrag] = useState('')
  const [mwstSatz, setMwstSatz] = useState('')
  const [buchungstext, setBuchungstext] = useState('')
  const [scope, setScope] = useState<LearnScope>('this_only')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit() {
    setSending(true)
    setError(null)
    try {
      const corrections: Record<string, string | number> = {}
      if (kontoSoll) corrections.konto_soll = kontoSoll
      if (kontoHaben) corrections.konto_haben = kontoHaben
      if (betrag) corrections.betrag = parseFloat(betrag)
      if (mwstSatz) corrections.mwst_satz = parseFloat(mwstSatz)
      if (buchungstext) corrections.buchungstext = buchungstext

      await api.post(`/inbox/${caseId}/approve`, {
        action: 'correct',
        corrections,
      })

      await api.post(`/inbox/${caseId}/learn`, {
        scope,
        rule: `Korrektur: Soll=${kontoSoll || '-'}, Haben=${kontoHaben || '-'}`,
      })

      onDone()
    } catch {
      setError('Korrektur konnte nicht gesendet werden.')
      setSending(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-scrim/40 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Dialog */}
      <Card variant="elevated" className="relative z-10 w-full max-w-lg mx-4 mb-4 max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <p className="text-sm font-semibold text-on-surface flex items-center gap-2">
            <Icon name="edit" size={18} className="text-primary" />
            Buchung korrigieren
          </p>
          <button onClick={onCancel} className="p-1 rounded-m3-sm hover:bg-surface-container-high transition-colors">
            <Icon name="close" size={20} className="text-on-surface-variant" />
          </button>
        </div>

        <div className="flex flex-col gap-3">
          <Input
            label="Konto Soll"
            value={kontoSoll}
            onChange={(e) => setKontoSoll(e.target.value)}
            placeholder={currentProposal?.skr03_soll_name ?? 'z.B. 4400'}
            disabled={sending}
          />
          <Input
            label="Konto Haben"
            value={kontoHaben}
            onChange={(e) => setKontoHaben(e.target.value)}
            placeholder={currentProposal?.skr03_haben_name ?? 'z.B. 1200'}
            disabled={sending}
          />
          <Input
            label="Betrag"
            type="number"
            value={betrag}
            onChange={(e) => setBetrag(e.target.value)}
            placeholder="0,00"
            disabled={sending}
          />
          <Input
            label="MwSt-Satz"
            type="number"
            value={mwstSatz}
            onChange={(e) => setMwstSatz(e.target.value)}
            placeholder="19"
            disabled={sending}
          />

          {/* Buchungstext as textarea styled like Input */}
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1">Buchungstext</label>
            <textarea
              className="w-full px-4 py-3 bg-surface-container-high text-on-surface rounded-m3-sm border border-outline-variant focus:border-primary focus:outline-none transition-colors resize-none"
              rows={2}
              value={buchungstext}
              onChange={(e) => setBuchungstext(e.target.value)}
              placeholder="Freitext zur Buchung"
              disabled={sending}
            />
          </div>
        </div>

        {/* Learn scope */}
        <p className="text-xs font-semibold text-on-surface-variant mt-4 mb-2">Lernregel</p>
        <div className="flex flex-wrap gap-2">
          {SCOPE_OPTIONS.map((opt) => (
            <Chip
              key={opt.value}
              label={opt.label}
              color={scope === opt.value ? 'primary' : 'default'}
              onClick={() => !sending && setScope(opt.value)}
            />
          ))}
        </div>

        {error && (
          <p className="text-xs text-error mt-3 flex items-center gap-1">
            <Icon name="error_outline" size={14} />
            {error}
          </p>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="text" onClick={onCancel} disabled={sending}>
            Abbrechen
          </Button>
          <Button variant="filled" icon="send" onClick={handleSubmit} disabled={sending}>
            {sending ? 'Wird gesendet…' : 'Korrektur senden'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
