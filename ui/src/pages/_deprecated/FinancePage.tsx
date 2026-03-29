import { useEffect, useState } from 'react'
import { Icon } from '../components/m3'
import { api } from '../lib/api'

interface FinanceSummary {
  period: string
  income: number
  expenses: number
  open_receivables: number
  open_payables: number
  overdue_count: number
  overdue_amount: number
}

type PeriodKey = 'month' | 'quarter' | 'year'

const MONTH_DE: Record<string, string> = {
  January: 'Januar', February: 'Februar', March: 'März', April: 'April',
  May: 'Mai', June: 'Juni', July: 'Juli', August: 'August',
  September: 'September', October: 'Oktober', November: 'November', December: 'Dezember',
}
function localizePeriod(s: string): string {
  return Object.entries(MONTH_DE).reduce((acc, [en, de]) => acc.replace(en, de), s)
}

const PERIOD_TABS: { key: PeriodKey; label: string }[] = [
  { key: 'month', label: 'Monat' },
  { key: 'quarter', label: 'Quartal' },
  { key: 'year', label: 'Jahr' },
]

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

interface MetricCardProps {
  icon: string
  label: string
  value: string
  iconColor?: string
}

function MetricCard({ icon, label, value, iconColor = 'text-on-surface-variant' }: MetricCardProps) {
  return (
    <div
      className="bg-surface-container rounded-[14px] p-4 flex flex-col items-center"
      style={{ padding: '16px' }}
    >
      <Icon name={icon} size={22} className={`${iconColor} mb-2`} />
      <p
        className="font-display font-bold text-on-surface text-center leading-tight"
        style={{ fontSize: '22px' }}
      >
        {value}
      </p>
      <p
        className="text-on-surface-variant text-center mt-1"
        style={{ fontSize: '11px' }}
      >
        {label}
      </p>
    </div>
  )
}

export function FinancePage() {
  const [data, setData] = useState<FinanceSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [period, setPeriod] = useState<PeriodKey>('month')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    async function load() {
      try {
        const result = await api.get<FinanceSummary>(`/finance/summary?period=${period}`)
        if (cancelled) return
        setData(result)
      } catch {
        if (!cancelled) setError('Finanzdaten konnten nicht geladen werden.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [period])

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--frya-surface)' }}>
      {/* TopBar */}
      <div className="bg-surface-container flex items-center gap-3 px-5 py-4">
        <Icon name="account_balance" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Finanzen</h1>
      </div>

      {/* Period Chips */}
      <div className="flex gap-2 px-4 py-3 overflow-x-auto">
        {PERIOD_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setPeriod(tab.key)}
            className={[
              'px-4 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap',
              period === tab.key
                ? 'bg-primary-container text-on-primary-container'
                : 'bg-surface-container text-on-surface-variant',
            ].join(' ')}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
        {loading && (
          <div className="grid grid-cols-2 gap-3 animate-pulse">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} style={{ backgroundColor: 'var(--frya-surface-container)', borderRadius: '14px', padding: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                <div style={{ width: '22px', height: '22px', borderRadius: '50%', backgroundColor: 'var(--frya-outline-variant)' }} />
                <div style={{ height: '22px', width: '80px', borderRadius: '6px', backgroundColor: 'var(--frya-outline-variant)' }} />
                <div style={{ height: '10px', width: '60px', borderRadius: '6px', backgroundColor: 'var(--frya-outline-variant)', opacity: 0.6 }} />
              </div>
            ))}
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-16">
            <Icon name="error" size={40} className="text-error mb-3" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {!loading && !error && data && (
          <>
            {/* Period label */}
            <p className="text-sm text-on-surface-variant text-center">{localizePeriod(data.period)}</p>

            {/* KPI Grid 2x2 */}
            <div className="grid grid-cols-2 gap-3">
              <MetricCard
                icon="trending_up"
                label="Einnahmen"
                value={amountFmt.format(data.income)}
                iconColor="text-success"
              />
              <MetricCard
                icon="trending_down"
                label="Ausgaben"
                value={amountFmt.format(data.expenses)}
                iconColor="text-error"
              />
              <MetricCard
                icon="receipt_long"
                label="Offene Forderungen"
                value={amountFmt.format(data.open_receivables)}
                iconColor="text-primary"
              />
              <MetricCard
                icon="payments"
                label="Offene Verbindl."
                value={amountFmt.format(data.open_payables)}
                iconColor="text-warning"
              />
            </div>

            {/* Overdue Warning Banner */}
            {data.overdue_count > 0 && (
              <div
                className="bg-warning-container rounded-[12px] px-4 py-3 flex items-center gap-3"
              >
                <Icon name="warning" size={22} className="text-warning flex-shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-warning">
                    {data.overdue_count} {data.overdue_count === 1 ? 'Vorgang' : 'Vorgänge'} überfällig
                  </p>
                  <p className="text-xs text-on-surface-variant mt-0.5">
                    Summe: {amountFmt.format(data.overdue_amount)}
                  </p>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
