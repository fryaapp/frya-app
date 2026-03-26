import { useEffect, useState } from 'react'
import { Card, Icon, Chip, Button } from '../m3'
import { api } from '../../lib/api'
import { CorrectionDialog } from './CorrectionDialog'

interface BookingProposal {
  skr03_soll: string
  skr03_soll_name: string
  skr03_haben: string
  skr03_haben_name: string
}

interface CaseDetail {
  case_id: string
  case_number: string
  vendor_name: string
  amount: number
  currency: string
  document_type: string
  status: string
  confidence: number
  confidence_label: string
  booking_proposal: BookingProposal
  document_analysis: {
    paperless_id: number
    extracted_fields: Record<string, string>
  }
  risk_report: unknown
  timeline: unknown
}

interface BelegDetailProps {
  caseId: string
  onClose: () => void
}

function FieldRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-baseline gap-4 py-1.5 border-b border-outline-variant/30 last:border-0">
      <span className="text-xs text-on-surface-variant shrink-0">{label}</span>
      <span className="text-sm text-on-surface text-right font-medium truncate">{value}</span>
    </div>
  )
}

const DOC_TYPE_LABELS: Record<string, string> = {
  INVOICE: 'Rechnung',
  CREDIT_NOTE: 'Gutschrift',
  RECEIPT: 'Beleg',
  REMINDER: 'Mahnung',
  CONTRACT: 'Vertrag',
}

function confidenceColor(c: number): 'success' | 'info' | 'warning' | 'error' | 'default' {
  if (c >= 0.85) return 'success'
  if (c >= 0.65) return 'info'
  if (c >= 0.40) return 'warning'
  return 'error'
}

function confidenceLabel(c: number): string {
  if (c >= 0.85) return 'Sicher'
  if (c >= 0.65) return 'Hoch'
  if (c >= 0.40) return 'Mittel'
  return 'Unsicher'
}

export function BelegDetail({ caseId, onClose }: BelegDetailProps) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionDone, setActionDone] = useState<string | null>(null)
  const [showCorrection, setShowCorrection] = useState(false)

  useEffect(() => {
    let revoke: string | null = null

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await api.get<CaseDetail>(`/cases/${caseId}`)
        setDetail(data)

        if (data.document_analysis?.paperless_id) {
          try {
            const blob = await api.getBlob(`/documents/${data.document_analysis.paperless_id}/thumbnail`)
            const url = URL.createObjectURL(blob)
            revoke = url
            setThumbUrl(url)
          } catch {
            /* Thumbnail nicht verfügbar — Platzhalter wird angezeigt */
          }
        }
      } catch {
        setError('Beleg konnte nicht geladen werden.')
      } finally {
        setLoading(false)
      }
    }

    load()

    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [caseId])

  async function handleAction(action: 'approve' | 'reject' | 'defer') {
    setActionLoading(true)
    try {
      await api.post(`/inbox/${caseId}/approve`, { action, corrections: null })
      const labels: Record<string, string> = {
        approve: 'Freigegeben',
        reject: 'Abgelehnt',
        defer: 'Zurückgestellt',
      }
      setActionDone(labels[action])
      setTimeout(() => onClose(), 1500)
    } catch {
      setActionLoading(false)
    }
  }

  function handleCorrectionDone() {
    setShowCorrection(false)
    setActionDone('Korrektur gesendet')
    setTimeout(() => onClose(), 1500)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full p-8">
        <Icon name="hourglass_empty" size={32} className="text-on-surface-variant animate-pulse" />
      </div>
    )
  }

  if (error || !detail) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 p-8">
        <Icon name="error_outline" size={32} className="text-error" />
        <p className="text-sm text-on-surface-variant">{error ?? 'Unbekannter Fehler'}</p>
        <button onClick={onClose} className="text-xs text-primary underline mt-2">Schließen</button>
      </div>
    )
  }

  const currency = detail.currency || 'EUR'
  const amount = new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(detail.amount)
  const fields = detail.document_analysis?.extracted_fields ?? {}
  const booking = detail.booking_proposal

  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant/30">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="receipt_long" size={20} className="text-primary shrink-0" />
          <span className="text-sm font-semibold text-on-surface truncate">{detail.vendor_name}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-lg font-display font-bold text-on-surface">{amount}</span>
          <button onClick={onClose} className="p-1 rounded-m3-sm hover:bg-surface-container-high transition-colors">
            <Icon name="close" size={20} className="text-on-surface-variant" />
          </button>
        </div>
      </div>

      {/* Thumbnail */}
      <div className="px-4 pt-3">
        {thumbUrl ? (
          <img
            src={thumbUrl}
            alt={`Vorschau: ${detail.case_number}`}
            className="w-full max-h-48 object-contain rounded-m3-sm bg-surface-container-high"
          />
        ) : (
          <div className="w-full h-32 rounded-m3-sm bg-surface-container-high flex items-center justify-center">
            <Icon name="description" size={40} className="text-on-surface-variant/40" />
          </div>
        )}
      </div>

      {/* Meta Chips */}
      <div className="flex flex-wrap gap-2 px-4 pt-3">
        <Chip label={DOC_TYPE_LABELS[detail.document_type] ?? detail.document_type} icon="category" />
        <Chip label={detail.case_number} icon="tag" />
        <Chip
          label={`${Math.round(detail.confidence * 100)}% ${confidenceLabel(detail.confidence)}`}
          color={confidenceColor(detail.confidence)}
          icon="speed"
        />
      </div>

      {/* Extrahierte Felder */}
      <Card variant="outlined" className="mx-4 mt-3">
        <p className="text-xs font-semibold text-on-surface-variant mb-2">Extrahierte Felder</p>
        {Object.entries(fields).map(([key, value]) => (
          <FieldRow key={key} label={key} value={String(value)} />
        ))}
        {Object.keys(fields).length === 0 && (
          <p className="text-xs text-on-surface-variant/60 py-2">Keine Felder extrahiert.</p>
        )}
      </Card>

      {/* Buchungsvorschlag */}
      {booking && (
        <Card variant="outlined" className="mx-4 mt-3 mb-4">
          <p className="text-xs text-on-surface-variant/70 flex items-center gap-1 mb-2">
            <Icon name="smart_toy" size={14} />
            KI-Vorschlag &middot; bitte pr&uuml;fen
          </p>
          <div className="flex items-center gap-2 text-sm text-on-surface">
            <div className="flex-1 rounded-m3-sm bg-surface-container-high px-3 py-2 text-center">
              <p className="text-xs text-on-surface-variant">Soll</p>
              <p className="font-semibold">{booking.skr03_soll}</p>
              <p className="text-xs text-on-surface-variant truncate">{booking.skr03_soll_name}</p>
            </div>
            <Icon name="arrow_forward" size={20} className="text-on-surface-variant shrink-0" />
            <div className="flex-1 rounded-m3-sm bg-surface-container-high px-3 py-2 text-center">
              <p className="text-xs text-on-surface-variant">Haben</p>
              <p className="font-semibold">{booking.skr03_haben}</p>
              <p className="text-xs text-on-surface-variant truncate">{booking.skr03_haben_name}</p>
            </div>
          </div>
        </Card>
      )}

      {/* Spacer so action bar doesn't cover content */}
      <div className="h-20 shrink-0" />

      {/* Sticky Action Bar */}
      <div className="sticky bottom-0 bg-surface border-t border-outline-variant/30 px-4 py-3">
        {actionDone ? (
          <div className="flex items-center justify-center gap-2 py-2">
            <Icon name="check_circle" size={20} className="text-success" />
            <span className="text-sm font-semibold text-on-surface">{actionDone}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Button
              variant="filled"
              icon="check"
              onClick={() => handleAction('approve')}
              disabled={actionLoading}
              className="flex-1"
            >
              Freigeben
            </Button>
            <Button
              variant="tonal"
              icon="edit"
              onClick={() => setShowCorrection(true)}
              disabled={actionLoading}
            >
              Korrigieren
            </Button>
            <Button
              variant="text"
              icon="close"
              onClick={() => handleAction('reject')}
              disabled={actionLoading}
            >
              Ablehnen
            </Button>
            <Button
              variant="text"
              icon="schedule"
              onClick={() => handleAction('defer')}
              disabled={actionLoading}
            >
              Sp&auml;ter
            </Button>
          </div>
        )}
      </div>

      {/* Correction Dialog */}
      {showCorrection && (
        <CorrectionDialog
          caseId={caseId}
          currentProposal={booking}
          onDone={handleCorrectionDone}
          onCancel={() => setShowCorrection(false)}
        />
      )}
    </div>
  )
}
