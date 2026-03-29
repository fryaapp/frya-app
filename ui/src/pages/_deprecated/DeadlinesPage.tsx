import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../components/m3'
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

const SECTION_META: Record<
  SectionKey,
  {
    label: string
    icon: string
    borderColor: string
    badgeBg: string
    badgeText: string
    emptyText: string
  }
> = {
  overdue: {
    label: 'Überfällig',
    icon: 'error',
    borderColor: 'var(--frya-error)',
    badgeBg: 'bg-error-container',
    badgeText: 'text-error',
    emptyText: 'Keine überfälligen Fristen.',
  },
  due_today: {
    label: 'Heute fällig',
    icon: 'today',
    borderColor: 'var(--frya-warning, #f59e0b)',
    badgeBg: 'bg-warning-container',
    badgeText: 'text-warning',
    emptyText: 'Heute nichts fällig.',
  },
  due_soon: {
    label: 'Bald fällig',
    icon: 'upcoming',
    borderColor: 'var(--frya-info, #3b82f6)',
    badgeBg: 'bg-primary-container',
    badgeText: 'text-primary',
    emptyText: 'Keine bald fälligen Fristen.',
  },
  skonto_expiring: {
    label: 'Skonto läuft ab',
    icon: 'savings',
    borderColor: 'var(--frya-warning, #f59e0b)',
    badgeBg: 'bg-warning-container',
    badgeText: 'text-warning',
    emptyText: 'Kein Skonto läuft ab.',
  },
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

function daysUntil(dateStr: string): number {
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  const target = new Date(dateStr)
  target.setHours(0, 0, 0, 0)
  return Math.round((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24))
}

function daysLabel(days: number): string {
  if (days < 0) return `${Math.abs(days)}d überfällig`
  if (days === 0) return 'Heute'
  return `${days}d`
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
    <div className="flex flex-col h-full" style={{ background: 'var(--frya-surface)' }}>
      {/* TopBar */}
      <div className="bg-surface-container flex items-center gap-3 px-5 py-4">
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
          <>
            {[0, 1, 2].map((i) => (
              <div key={i} className="animate-pulse" style={{ backgroundColor: 'var(--frya-surface-container)', borderRadius: '12px', padding: '11px 13px', borderLeft: '3px solid var(--frya-outline-variant)' }}>
                <div className="flex justify-between items-start">
                  <div style={{ height: '13px', width: '150px', borderRadius: '6px', backgroundColor: 'var(--frya-outline-variant)' }} />
                  <div style={{ height: '18px', width: '40px', borderRadius: '14px', backgroundColor: 'var(--frya-outline-variant)', opacity: 0.5 }} />
                </div>
                <div className="mt-2" style={{ height: '10px', width: '100px', borderRadius: '6px', backgroundColor: 'var(--frya-outline-variant)', opacity: 0.5 }} />
              </div>
            ))}
          </>
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
          const meta = SECTION_META[sectionKey]

          return (
            <div key={sectionKey}>
              {/* Section Header */}
              <div className="flex items-center gap-2 mb-2 px-0.5">
                <Icon name={meta.icon} size={15} className="text-on-surface-variant" />
                <h2
                  className="text-on-surface-variant font-semibold uppercase tracking-wider"
                  style={{ fontSize: '11px', letterSpacing: '0.08em' }}
                >
                  {meta.label}
                  {items.length > 0 && (
                    <span className="ml-1.5 normal-case font-normal">({items.length})</span>
                  )}
                </h2>
              </div>

              {/* Empty state per section */}
              {items.length === 0 && (
                <p className="text-xs text-on-surface-variant px-1 pb-1 italic">
                  {meta.emptyText}
                </p>
              )}

              {/* Deadline Cards */}
              {items.length > 0 && (
                <div className="space-y-2">
                  {items.map((item) => {
                    const days = daysUntil(item.due_date)

                    return (
                      <div
                        key={item.id}
                        className={[
                          'bg-surface-container relative',
                          item.case_id
                            ? 'cursor-pointer hover:bg-surface-container-high transition-colors'
                            : '',
                        ].join(' ')}
                        style={{
                          borderRadius: '12px',
                          padding: '11px 13px',
                          borderLeft: `3px solid ${meta.borderColor}`,
                        }}
                        onClick={item.case_id ? () => navigate(`/cases/${item.case_id}`) : undefined}
                        onKeyDown={
                          item.case_id
                            ? (e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  e.preventDefault()
                                  navigate(`/cases/${item.case_id}`)
                                }
                              }
                            : undefined
                        }
                        role={item.case_id ? 'button' : undefined}
                        tabIndex={item.case_id ? 0 : undefined}
                      >
                        {/* Days badge top-right */}
                        <span
                          className={`absolute top-2.5 right-3 text-[11px] font-semibold ${meta.badgeText} ${meta.badgeBg} px-2 py-0.5 rounded-full`}
                        >
                          {daysLabel(days)}
                        </span>

                        {/* Title + meta row */}
                        <p className="text-sm font-semibold text-on-surface truncate pr-20">
                          {item.title}
                        </p>

                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className="text-xs text-on-surface-variant">
                            {formatDate(item.due_date)}
                          </span>
                          {item.type && (
                            <span className="text-xs text-on-surface-variant">
                              &middot; {TYPE_LABELS[item.type] ?? item.type}
                            </span>
                          )}
                          {item.amount != null && item.currency && (
                            <span className="text-xs font-semibold text-on-surface font-display ml-auto">
                              {formatAmount(item.amount, item.currency)}
                            </span>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
