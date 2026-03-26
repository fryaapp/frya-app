import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Chip, Icon, ConfidenceBadge, StatusBadge } from '../components/m3'
import { api } from '../lib/api'

interface CaseItem {
  case_id: string
  case_number: string
  vendor_name: string
  amount: number
  currency: string
  document_type: string
  status: string
  confidence: number | null
  confidence_label: string
  risk_flags: string[]
  conflicts: string[]
}

interface CasesResponse {
  items: CaseItem[]
}

type FilterKey = 'ALL' | 'OPEN' | 'DRAFT' | 'ANALYZED' | 'PROPOSED' | 'APPROVED' | 'OVERDUE' | 'BOOKED'

const FILTERS: { key: FilterKey; label: string; icon: string }[] = [
  { key: 'ALL', label: 'Alle', icon: 'list' },
  { key: 'OPEN', label: 'Offen', icon: 'folder_open' },
  { key: 'DRAFT', label: 'Entwurf', icon: 'edit_note' },
  { key: 'ANALYZED', label: 'Analysiert', icon: 'analytics' },
  { key: 'PROPOSED', label: 'Vorgeschlagen', icon: 'auto_awesome' },
  { key: 'APPROVED', label: 'Genehmigt', icon: 'thumb_up' },
  { key: 'OVERDUE', label: 'Überfällig', icon: 'schedule' },
  { key: 'BOOKED', label: 'Gebucht', icon: 'check_circle' },
]

const CONFLICT_LABELS: Record<string, string> = {
  MISSING_REFERENCE: 'Fehlende Referenz',
  AMBIGUOUS_ASSIGNMENT: 'Mehrdeutige Zuordnung',
}

const RISK_FLAG_LABELS: Record<string, string> = {
  amount_consistency: 'Betragsabweichung',
  duplicate_detection: 'Duplikat erkannt',
  tax_plausibility: 'Steuer prüfen',
  vendor_consistency: 'Absender prüfen',
  booking_plausibility: 'Buchung prüfen',
}

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(amount: number, currency: string): string {
  if (currency === 'EUR') return amountFmt.format(amount)
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(amount)
}

export function CasesPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<CaseItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterKey>('ALL')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      try {
        const statusParam = filter === 'ALL' ? '' : filter
        const data = await api.get<CasesResponse>(`/cases?status=${statusParam}&limit=50`)
        if (cancelled) return
        setItems(data.items)
      } catch {
        if (!cancelled) setError('Vorgänge konnten nicht geladen werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [filter])

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="folder_copy" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Vorgänge</h1>
        {items.length > 0 && (
          <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-primary text-on-primary text-xs font-bold">
            {items.length}
          </span>
        )}
      </div>

      {/* Filter Chips */}
      <div className="flex gap-2 px-4 py-3 overflow-x-auto">
        {FILTERS.map((f) => (
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
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Vorgänge&hellip;</p>
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
            <p className="text-sm font-medium">Keine Vorgänge gefunden.</p>
          </div>
        )}

        {!loading && !error && items.map((item) => (
          <Card
            key={item.case_id}
            variant="outlined"
            onClick={() => navigate(`/cases/${item.case_id}`)}
          >
            {/* Header row */}
            <div className="flex items-start justify-between gap-2 mb-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-on-surface truncate">
                  {item.vendor_name || 'Unbekannter Absender'}
                </p>
                <p className="text-xs text-on-surface-variant">
                  {item.case_number}
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
              <StatusBadge status={item.status} />
              <ConfidenceBadge confidence={item.confidence} />
            </div>

            {/* Conflicts */}
            {item.conflicts?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {item.conflicts.map((conflict) => (
                  <Chip
                    key={conflict}
                    label={CONFLICT_LABELS[conflict] ?? conflict}
                    icon="error"
                    color="error"
                  />
                ))}
              </div>
            )}

            {/* Risk flags */}
            {item.risk_flags?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {item.risk_flags.map((flag) => (
                  <Chip
                    key={flag}
                    label={RISK_FLAG_LABELS[flag] ?? flag}
                    icon="warning"
                    color="warning"
                  />
                ))}
              </div>
            )}
          </Card>
        ))}
      </div>
    </div>
  )
}
