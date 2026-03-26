import { useCallback, useEffect, useState } from 'react'
import { Card, Icon, Chip, ConfidenceBadge, StatusBadge, Button } from '../m3'
import { api } from '../../lib/api'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface LineItem {
  description: string
  quantity: number
  unit_price: string
  total_price: string
}

interface TimelineEvent {
  timestamp: string
  event_type: string
  description: string
  agent?: string
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
  net_amount?: number
  tax_rate?: number
  tax_amount?: number
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
  line_items?: LineItem[]
}

interface CaseDetailProps {
  caseId: string
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

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

const AGENT_LABELS: Record<string, string> = {
  orchestrator: 'Orchestrator',
  communicator: 'Kommunikator',
  document_analyst: 'Dokumentanalyse',
  document_analyst_semantic: 'Semantische Analyse',
  accounting_analyst: 'Buchhaltung',
  deadline_analyst: 'Fristenanalyse',
  risk_consistency: 'Risiko & Konsistenz',
  memory_curator: 'Gedächtnis',
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(amount: number, currency: string): string {
  if (currency === 'EUR') return amountFmt.format(amount)
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(amount)
}

function formatEur(value: number): string {
  return amountFmt.format(value)
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

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function CaseDetail({ caseId }: CaseDetailProps) {
  const [data, setData] = useState<CaseDetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  const loadCase = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const result = await api.get<CaseDetailData>(`/cases/${caseId}`)
      setData(result)
    } catch {
      setError('Vorgang konnte nicht geladen werden.')
    } finally {
      setLoading(false)
    }
  }, [caseId])

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

  /* ---- Approval Actions ---- */

  async function handleAction(action: 'approve' | 'reject' | 'correct' | 'defer') {
    if (!data) return
    try {
      setActionLoading(true)
      await api.post(`/inbox/${data.case_id}/approve`, { action })
      await loadCase()
    } catch {
      setError('Aktion konnte nicht ausgeführt werden.')
    } finally {
      setActionLoading(false)
    }
  }

  /* ---- Render states ---- */

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

  const da = data.document_analysis
  const hasTaxInfo = da && (da.net_amount != null || da.tax_rate != null)
  const hasLineItems = data.line_items && data.line_items.length > 0
  const showActionButtons = data.status === 'DRAFT' || data.status === 'PROPOSED'
  const isTerminal = data.status === 'BOOKED' || data.status === 'PAID'
  const isApproved = data.status === 'APPROVED'

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

      {/* Line Items (Positionen) */}
      {hasLineItems && (
        <Card variant="outlined">
          <div className="flex items-center gap-2 mb-3">
            <Icon name="receipt_long" size={18} className="text-on-surface-variant" />
            <p className="text-sm font-semibold text-on-surface">Positionen</p>
          </div>
          <div className="space-y-2">
            {data.line_items!.map((item, idx) => (
              <div key={idx} className="flex items-start justify-between gap-2 text-sm">
                <p className="flex-1 text-on-surface">{item.description}</p>
                <p className="text-on-surface-variant whitespace-nowrap">
                  {item.quantity}x
                </p>
                <p className="font-semibold text-on-surface whitespace-nowrap">
                  {formatEur(parseFloat(item.total_price))}
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* MwSt-Aufschlüsselung */}
      {hasTaxInfo && da && (
        <Card variant="outlined">
          <div className="flex items-center gap-2 mb-3">
            <Icon name="percent" size={18} className="text-on-surface-variant" />
            <p className="text-sm font-semibold text-on-surface">MwSt-Aufschlüsselung</p>
          </div>
          <div className="space-y-1.5 text-sm">
            {da.net_amount != null && (
              <div className="flex justify-between">
                <span className="text-on-surface-variant">Netto</span>
                <span className="text-on-surface font-semibold">{formatEur(da.net_amount)}</span>
              </div>
            )}
            {da.tax_rate != null && (
              <div className="flex justify-between">
                <span className="text-on-surface-variant">MwSt-Satz</span>
                <span className="text-on-surface font-semibold">{da.tax_rate}\u2009%</span>
              </div>
            )}
            {da.tax_amount != null && (
              <div className="flex justify-between">
                <span className="text-on-surface-variant">MwSt-Betrag</span>
                <span className="text-on-surface font-semibold">{formatEur(da.tax_amount)}</span>
              </div>
            )}
            <div className="flex justify-between border-t border-outline-variant pt-1.5">
              <span className="text-on-surface-variant">Brutto</span>
              <span className="text-on-surface font-bold">{formatEur(da.amount)}</span>
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
                    {event.agent && (
                      <span className="font-medium">
                        {AGENT_LABELS[event.agent] ?? event.agent}
                        {' · '}
                      </span>
                    )}
                    {formatTimestamp(event.timestamp)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Buttons */}
      {showActionButtons && (
        <div className="grid grid-cols-2 gap-2 pt-2">
          <Button
            variant="filled"
            icon="check"
            onClick={() => handleAction('approve')}
            disabled={actionLoading}
          >
            Freigeben
          </Button>
          <Button
            variant="outlined"
            icon="edit"
            onClick={() => handleAction('correct')}
            disabled={actionLoading}
          >
            Korrigieren
          </Button>
          <Button
            variant="outlined"
            icon="close"
            onClick={() => handleAction('reject')}
            disabled={actionLoading}
            className="text-error border-error"
          >
            Ablehnen
          </Button>
          <Button
            variant="text"
            icon="schedule"
            onClick={() => handleAction('defer')}
            disabled={actionLoading}
          >
            Später
          </Button>
        </div>
      )}

      {isApproved && (
        <div className="flex items-center gap-2 py-3 px-4 rounded-m3-xl bg-secondary-container">
          <Icon name="verified" size={20} className="text-on-secondary-container" />
          <p className="text-sm font-semibold text-on-secondary-container">
            Bereits freigegeben
          </p>
        </div>
      )}

      {isTerminal && (
        <div className="flex items-center gap-2 py-3 px-4 rounded-m3-xl bg-surface-container-high">
          <Icon name="info" size={20} className="text-on-surface-variant" />
          <p className="text-sm text-on-surface-variant">
            Vorgang abgeschlossen ({data.status === 'BOOKED' ? 'Gebucht' : 'Bezahlt'})
          </p>
        </div>
      )}
    </div>
  )
}
