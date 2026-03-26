import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Chip, Icon, ConfidenceBadge } from '../components/m3'
import { api } from '../lib/api'

interface BookingProposal {
  skr03_soll: string
  skr03_soll_name: string
  skr03_haben: string
  skr03_haben_name: string
}

interface InboxItem {
  case_id: string
  case_number: string
  vendor_name: string
  amount: number
  currency: string
  document_type: string
  status: string
  approval_mode: string
  confidence: number | null
  confidence_label: string
  due_date: string | null
  risk_flags: string[]
  booking_proposal: BookingProposal | null
}

interface InboxResponse {
  count: number
  items: InboxItem[]
}

const RISK_FLAG_LABELS: Record<string, string> = {
  amount_consistency: 'Betragsabweichung',
  duplicate_detection: 'Duplikat erkannt',
  tax_plausibility: 'Steuer prüfen',
  vendor_consistency: 'Absender prüfen',
  booking_plausibility: 'Buchung prüfen',
}

const DOC_TYPE_LABELS: Record<string, string> = {
  INVOICE: 'Rechnung',
  CREDIT_NOTE: 'Gutschrift',
  RECEIPT: 'Beleg',
}

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(amount: number, currency: string): string {
  if (currency === 'EUR') return amountFmt.format(amount)
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(amount)
}

type InboxFilter = 'pending' | 'approved' | 'rejected'

const INBOX_FILTERS: { key: InboxFilter; label: string; icon: string }[] = [
  { key: 'pending', label: 'Ausstehend', icon: 'hourglass_empty' },
  { key: 'approved', label: 'Freigegeben', icon: 'check_circle' },
  { key: 'rejected', label: 'Abgelehnt', icon: 'cancel' },
]

export function InboxPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<InboxItem[]>([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<InboxFilter>('pending')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      try {
        const data = await api.get<InboxResponse>(`/inbox?status=${filter}&limit=50`)
        if (cancelled) return
        setItems(data.items)
        setCount(data.count)
      } catch {
        if (!cancelled) setError('Inbox konnte nicht geladen werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [filter])

  const handleCardClick = (caseId: string) => {
    navigate(`/inbox/${caseId}`)
  }

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="inbox" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Inbox</h1>
        {count > 0 && (
          <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-primary text-on-primary text-xs font-bold">
            {count}
          </span>
        )}
      </div>

      {/* Filter Chips */}
      <div className="flex gap-2 px-4 py-3 overflow-x-auto">
        {INBOX_FILTERS.map((f) => (
          <Chip
            key={f.key}
            label={f.label}
            icon={f.icon}
            color={filter === f.key ? 'primary' : 'default'}
            onClick={() => setFilter(f.key)}
          />
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Belege&hellip;</p>
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-16">
            <Icon name="error" size={40} className="text-error mb-3" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="check_circle" size={48} className="text-success mb-3" />
            <p className="text-sm font-medium">Keine offenen Belege &mdash; alles erledigt!</p>
          </div>
        )}

        {!loading && !error && items.map((item) => {
          const needsApproval = item.approval_mode === 'REQUIRE_USER_APPROVAL'

          return (
            <Card
              key={item.case_id}
              variant="outlined"
              className={needsApproval ? 'border-l-[3px] border-l-error' : ''}
              onClick={() => handleCardClick(item.case_id)}
            >
              {/* Header row */}
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-on-surface truncate">
                    {item.vendor_name || 'Unbekannter Absender'}
                  </p>
                  <p className="text-xs text-on-surface-variant">
                    {DOC_TYPE_LABELS[item.document_type] ?? item.document_type}
                  </p>
                </div>
                {item.amount != null && (
                  <p className="text-base font-bold text-on-surface whitespace-nowrap">
                    {formatAmount(item.amount, item.currency)}
                  </p>
                )}
              </div>

              {/* Badges row */}
              <div className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge confidence={item.confidence} />

                {item.booking_proposal && (
                  <Chip
                    label="KI-Vorschlag · bitte prüfen"
                    icon="auto_awesome"
                    color="info"
                    className="text-[10px]"
                  />
                )}
              </div>

              {/* Risk flags */}
              {item.risk_flags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {item.risk_flags.map((flag) => (
                    <Chip
                      key={flag}
                      label={RISK_FLAG_LABELS[flag] ?? flag}
                      icon="warning"
                      color="error"
                    />
                  ))}
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </div>
  )
}
