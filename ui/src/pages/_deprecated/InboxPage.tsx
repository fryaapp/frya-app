import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon, ConfidenceBadge } from '../components/m3'
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
    <div
      className="flex flex-col h-full"
      style={{ backgroundColor: 'var(--frya-surface)' }}
    >
      {/* TopBar */}
      <div
        className="flex items-center gap-3 px-5 py-4 bg-surface-container"
        style={{ borderBottom: '1px solid var(--frya-outline-variant)' }}
      >
        <Icon name="inbox" size={24} className="text-primary" />
        <h1 className="text-lg font-bold text-on-surface" style={{ fontFamily: 'Outfit, sans-serif' }}>
          Inbox
        </h1>
        {count > 0 && (
          <span
            className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 bg-primary text-on-primary text-xs font-bold"
            style={{ borderRadius: '11px', fontFamily: 'Outfit, sans-serif' }}
          >
            {count}
          </span>
        )}
      </div>

      {/* Filter Chips */}
      <div className="flex gap-2 px-5 py-3 overflow-x-auto" style={{ backgroundColor: 'var(--frya-surface)' }}>
        {INBOX_FILTERS.map((f) => {
          const isActive = filter === f.key
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className="inline-flex items-center gap-1.5 text-xs font-medium transition-all whitespace-nowrap"
              style={{
                borderRadius: '18px',
                padding: '6px 14px',
                border: isActive ? '1px solid transparent' : '1px solid var(--frya-outline-variant)',
                backgroundColor: isActive ? 'var(--frya-primary-container)' : 'transparent',
                color: isActive ? 'var(--frya-on-primary-container)' : 'var(--frya-on-surface-variant)',
                cursor: 'pointer',
              }}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 15 }}>{f.icon}</span>
              {f.label}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2.5">

        {/* Loading skeleton */}
        {loading && (
          <>
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="animate-pulse"
                style={{
                  backgroundColor: 'var(--frya-surface-container)',
                  borderRadius: '12px',
                  padding: '11px 13px',
                }}
              >
                <div className="flex justify-between items-start mb-2">
                  <div>
                    <div
                      className="mb-1.5"
                      style={{
                        height: '13px',
                        width: '120px',
                        borderRadius: '6px',
                        backgroundColor: 'var(--frya-outline-variant)',
                      }}
                    />
                    <div
                      style={{
                        height: '10px',
                        width: '72px',
                        borderRadius: '6px',
                        backgroundColor: 'var(--frya-outline-variant)',
                        opacity: 0.6,
                      }}
                    />
                  </div>
                  <div
                    style={{
                      height: '16px',
                      width: '64px',
                      borderRadius: '6px',
                      backgroundColor: 'var(--frya-outline-variant)',
                    }}
                  />
                </div>
                <div className="flex gap-2 mt-2">
                  <div
                    style={{
                      height: '18px',
                      width: '50px',
                      borderRadius: '14px',
                      backgroundColor: 'var(--frya-outline-variant)',
                      opacity: 0.5,
                    }}
                  />
                  <div
                    style={{
                      height: '18px',
                      width: '90px',
                      borderRadius: '14px',
                      backgroundColor: 'var(--frya-outline-variant)',
                      opacity: 0.4,
                    }}
                  />
                </div>
              </div>
            ))}
          </>
        )}

        {/* Error state */}
        {!loading && error && (
          <div
            className="flex items-start gap-3 px-4 py-4"
            style={{
              backgroundColor: 'var(--frya-error-container)',
              borderRadius: '12px',
              color: 'var(--frya-error)',
            }}
          >
            <Icon name="error_outline" size={22} />
            <p className="text-sm font-medium">{error}</p>
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <Icon name="check_circle" size={48} className="text-success" />
            <p className="text-sm font-medium text-on-surface-variant">
              Keine offenen Belege &mdash; alles erledigt!
            </p>
          </div>
        )}

        {/* Item cards */}
        {!loading && !error && items.map((item) => {
          const needsApproval = item.approval_mode === 'REQUIRE_USER_APPROVAL'

          return (
            <div
              key={item.case_id}
              role="button"
              tabIndex={0}
              onClick={() => handleCardClick(item.case_id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  handleCardClick(item.case_id)
                }
              }}
              style={{
                backgroundColor: 'var(--frya-surface-container)',
                borderRadius: '12px',
                padding: '11px 13px',
                borderLeft: needsApproval ? '3px solid var(--frya-error)' : '3px solid transparent',
                cursor: 'pointer',
                transition: 'background-color 0.15s ease',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--frya-surface-container-high)'
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.backgroundColor = 'var(--frya-surface-container)'
              }}
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
                  <p
                    className="text-base font-bold text-on-surface whitespace-nowrap"
                    style={{ fontFamily: 'Outfit, sans-serif', textAlign: 'right' }}
                  >
                    {formatAmount(item.amount, item.currency)}
                  </p>
                )}
              </div>

              {/* Badges row */}
              <div className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge confidence={item.confidence} />

                {item.booking_proposal && (
                  <span
                    className="inline-flex items-center gap-1 font-medium"
                    style={{
                      fontSize: '10px',
                      padding: '2px 7px',
                      borderRadius: '14px',
                      backgroundColor: 'var(--frya-info-container)',
                      color: 'var(--frya-info)',
                    }}
                  >
                    <span className="material-symbols-rounded" style={{ fontSize: 12 }}>auto_awesome</span>
                    KI-Vorschlag &middot; bitte prüfen
                  </span>
                )}
              </div>

              {/* Risk flags */}
              {item.risk_flags?.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mt-2">
                  {item.risk_flags.map((flag) => (
                    <span
                      key={flag}
                      className="inline-flex items-center gap-1 font-medium"
                      style={{
                        fontSize: '10px',
                        padding: '2px 7px',
                        borderRadius: '14px',
                        backgroundColor: 'var(--frya-warning-container)',
                        color: 'var(--frya-warning)',
                      }}
                    >
                      <span className="material-symbols-rounded" style={{ fontSize: 12 }}>warning</span>
                      {RISK_FLAG_LABELS[flag] ?? flag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
