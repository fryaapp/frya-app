import { useEffect, useState } from 'react'
import { Card, Icon, Chip, ConfidenceBadge, StatusBadge } from '../m3'
import { api } from '../../lib/api'

interface TimelineEvent {
  timestamp: string
  event_type: string
  description: string
}

interface BookingProposal {
  skr03_soll: string
  skr03_soll_name: string
  skr03_haben: string
  skr03_haben_name: string
}

interface RiskReport {
  flags: string[]
  score: number
}

interface DocumentAnalysis {
  vendor_name: string
  amount: number
  currency: string
  document_type: string
}

interface CaseDetailData {
  case_id: string
  case_number: string
  vendor_name: string
  amount: number
  currency: string
  status: string
  confidence: number | null
  confidence_label: string
  document_analysis: DocumentAnalysis | null
  booking_proposal: BookingProposal | null
  risk_report: RiskReport | null
  timeline: TimelineEvent[]
}

interface CaseDetailProps {
  caseId: string
}

const RISK_FLAG_LABELS: Record<string, string> = {
  amount_consistency: 'Betragsabweichung',
  duplicate_detection: 'Duplikat erkannt',
  tax_plausibility: 'Steuer prüfen',
  vendor_consistency: 'Absender prüfen',
  booking_plausibility: 'Buchung prüfen',
}

const EVENT_ICONS: Record<string, string> = {
  CREATED: 'add_circle',
  UPLOADED: 'upload_file',
  ANALYZED: 'auto_awesome',
  BOOKED: 'check_circle',
  APPROVED: 'verified',
  REJECTED: 'cancel',
  PAID: 'payments',
  OVERDUE: 'schedule',
}

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(amount: number, currency: string): string {
  if (currency === 'EUR') return amountFmt.format(amount)
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(amount)
}

function formatTimestamp(ts: string): string {
  return new Date(ts).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function CaseDetail({ caseId }: CaseDetailProps) {
  const [data, setData] = useState<CaseDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const result = await api.get<CaseDetailData>(`/cases/${caseId}`)
        if (cancelled) return
        setData(result)
      } catch {
        if (!cancelled) setError('Vorgang konnte nicht geladen werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [caseId])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
        <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
        <p className="text-sm">Lade Vorgang&hellip;</p>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <Icon name="error" size={40} className="text-error mb-3" />
        <p className="text-sm text-error">{error ?? 'Unbekannter Fehler'}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto">
      {/* Header */}
      <div>
        <h2 className="text-lg font-display font-bold text-on-surface">{data.vendor_name}</h2>
        <p className="text-xs text-on-surface-variant">{data.case_number}</p>
      </div>

      {/* Amount + Badges */}
      <div className="flex items-center justify-between">
        <p className="text-2xl font-bold text-on-surface">
          {formatAmount(data.amount, data.currency)}
        </p>
        <div className="flex items-center gap-2">
          <StatusBadge status={data.status} />
          <ConfidenceBadge confidence={data.confidence} />
        </div>
      </div>

      {/* Booking Proposal */}
      {data.booking_proposal && (
        <Card variant="outlined" className="border-l-[3px] border-l-info">
          <div className="flex items-center gap-2 mb-2">
            <Icon name="auto_awesome" size={18} className="text-info" />
            <p className="text-xs font-semibold text-info">
              KI-Vorschlag &middot; bitte prüfen
            </p>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-xs text-on-surface-variant">Soll</p>
              <p className="font-semibold text-on-surface">
                {data.booking_proposal.skr03_soll} {data.booking_proposal.skr03_soll_name}
              </p>
            </div>
            <div>
              <p className="text-xs text-on-surface-variant">Haben</p>
              <p className="font-semibold text-on-surface">
                {data.booking_proposal.skr03_haben} {data.booking_proposal.skr03_haben_name}
              </p>
            </div>
          </div>
        </Card>
      )}

      {/* Risk Report */}
      {data.risk_report && data.risk_report.flags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.risk_report.flags.map((flag) => (
            <Chip key={flag} label={RISK_FLAG_LABELS[flag] ?? flag} icon="warning" color="error" />
          ))}
        </div>
      )}

      {/* Timeline */}
      {data.timeline.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-on-surface mb-3">Verlauf</h3>
          <div className="relative pl-6 space-y-4">
            {/* Vertical line */}
            <div className="absolute left-[11px] top-1 bottom-1 w-px bg-outline-variant" />

            {data.timeline.map((event, idx) => (
              <div key={idx} className="relative flex gap-3 items-start">
                <div className="absolute -left-6 w-[22px] h-[22px] rounded-full bg-surface-container-high flex items-center justify-center z-10">
                  <Icon
                    name={EVENT_ICONS[event.event_type] ?? 'circle'}
                    size={14}
                    className="text-on-surface-variant"
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-on-surface">{event.description}</p>
                  <p className="text-xs text-on-surface-variant">
                    {formatTimestamp(event.timestamp)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
