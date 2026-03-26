import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Icon } from '../components/m3'
import { api } from '../lib/api'

interface DeadlineItem {
  id: string
  title: string
  due_date: string
  type: string
  amount: number | null
  currency: string | null
  case_id: string | null
}

interface DeadlinesResponse {
  overdue: DeadlineItem[]
  due_today: DeadlineItem[]
  due_soon: DeadlineItem[]
  skonto_expiring: DeadlineItem[]
  summary: string
}

type SectionKey = 'overdue' | 'due_today' | 'due_soon' | 'skonto_expiring'

const SECTION_META: Record<SectionKey, { label: string; icon: string; borderClass: string }> = {
  overdue: { label: 'Überfällig', icon: 'error', borderClass: 'border-l-4 border-l-error' },
  due_today: { label: 'Heute fällig', icon: 'today', borderClass: 'border-l-4 border-l-warning' },
  due_soon: { label: 'Bald fällig', icon: 'upcoming', borderClass: 'border-l-4 border-l-success' },
  skonto_expiring: { label: 'Skonto läuft ab', icon: 'savings', borderClass: 'border-l-4 border-l-info' },
}

const SECTION_ORDER: SectionKey[] = ['overdue', 'due_today', 'due_soon', 'skonto_expiring']

const TYPE_LABELS: Record<string, string> = {
  skonto: 'Skonto',
  kuendigung: 'Kündigung',
  einspruch: 'Einspruch',
  zahlung: 'Zahlung',
  faelligkeit: 'Fälligkeit',
}

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

function formatAmount(amount: number, currency: string): string {
  if (currency === 'EUR') return amountFmt.format(amount)
  return new Intl.NumberFormat('de-DE', { style: 'currency', currency }).format(amount)
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function DeadlinesPage() {
  const navigate = useNavigate()
  const [data, setData] = useState<DeadlinesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const result = await api.get<DeadlinesResponse>('/deadlines')
        if (cancelled) return
        setData(result)
      } catch {
        if (!cancelled) setError('Fristen konnten nicht geladen werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  const totalCount = data
    ? data.overdue.length + data.due_today.length + data.due_soon.length + data.skonto_expiring.length
    : 0

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="event" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Fristen</h1>
        {totalCount > 0 && (
          <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-primary text-on-primary text-xs font-bold">
            {totalCount}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Fristen&hellip;</p>
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-16">
            <Icon name="error" size={40} className="text-error mb-3" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {!loading && !error && totalCount === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="check_circle" size={48} className="text-success mb-3" />
            <p className="text-sm font-medium">Keine offenen Fristen.</p>
          </div>
        )}

        {!loading && !error && data && SECTION_ORDER.map((sectionKey) => {
          const items = data[sectionKey]
          if (items.length === 0) return null

          const meta = SECTION_META[sectionKey]

          return (
            <div key={sectionKey}>
              <div className="flex items-center gap-2 mb-2">
                <Icon name={meta.icon} size={18} className="text-on-surface-variant" />
                <h2 className="text-sm font-semibold text-on-surface-variant">
                  {meta.label} ({items.length})
                </h2>
              </div>

              <div className="space-y-2">
                {items.map((item) => (
                  <Card
                    key={item.id}
                    variant="outlined"
                    className={meta.borderClass}
                    onClick={item.case_id ? () => navigate(`/cases/${item.case_id}`) : undefined}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-on-surface truncate">
                          {item.title}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <p className="text-xs text-on-surface-variant">
                            {formatDate(item.due_date)}
                          </p>
                          {item.type && (
                            <span className="text-xs text-on-surface-variant">
                              &middot; {TYPE_LABELS[item.type] ?? item.type}
                            </span>
                          )}
                        </div>
                      </div>
                      {item.amount != null && item.currency && (
                        <p className="text-sm font-bold text-on-surface whitespace-nowrap">
                          {formatAmount(item.amount, item.currency)}
                        </p>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
