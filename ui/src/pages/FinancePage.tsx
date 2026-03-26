import { useEffect, useState } from 'react'
import { Card, Chip, Icon } from '../components/m3'
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

const PERIOD_TABS: { key: PeriodKey; label: string }[] = [
  { key: 'month', label: 'Monat' },
  { key: 'quarter', label: 'Quartal' },
  { key: 'year', label: 'Jahr' },
]

const amountFmt = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'EUR',
})

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
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="account_balance" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Finanzen</h1>
      </div>

      {/* Period Tabs */}
      <div className="flex gap-2 px-4 py-3 overflow-x-auto">
        {PERIOD_TABS.map((tab) => (
          <Chip
            key={tab.key}
            label={tab.label}
            color={period === tab.key ? 'primary' : 'default'}
            onClick={() => setPeriod(tab.key)}
          />
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Finanzdaten&hellip;</p>
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
            <p className="text-sm text-on-surface-variant text-center">{data.period}</p>

            {/* KPI Grid 2x2 */}
            <div className="grid grid-cols-2 gap-3">
              {/* Einnahmen */}
              <Card variant="filled" className="border-l-4 border-l-success">
                <div className="flex items-center gap-2 mb-2">
                  <Icon name="trending_up" size={18} className="text-success" />
                  <p className="text-xs font-medium text-on-surface-variant">Einnahmen</p>
                </div>
                <p className="text-lg font-bold text-on-surface">
                  {amountFmt.format(data.income)}
                </p>
              </Card>

              {/* Ausgaben */}
              <Card variant="filled" className="border-l-4 border-l-error">
                <div className="flex items-center gap-2 mb-2">
                  <Icon name="trending_down" size={18} className="text-error" />
                  <p className="text-xs font-medium text-on-surface-variant">Ausgaben</p>
                </div>
                <p className="text-lg font-bold text-on-surface">
                  {amountFmt.format(data.expenses)}
                </p>
              </Card>

              {/* Offene Forderungen */}
              <Card variant="filled">
                <div className="flex items-center gap-2 mb-2">
                  <Icon name="receipt_long" size={18} className="text-on-surface-variant" />
                  <p className="text-xs font-medium text-on-surface-variant">Offene Forderungen</p>
                </div>
                <p className="text-lg font-bold text-on-surface">
                  {amountFmt.format(data.open_receivables)}
                </p>
              </Card>

              {/* Offene Verbindlichkeiten */}
              <Card variant="filled">
                <div className="flex items-center gap-2 mb-2">
                  <Icon name="payments" size={18} className="text-on-surface-variant" />
                  <p className="text-xs font-medium text-on-surface-variant">Offene Verbindl.</p>
                </div>
                <p className="text-lg font-bold text-on-surface">
                  {amountFmt.format(data.open_payables)}
                </p>
              </Card>
            </div>

            {/* Overdue Warning */}
            {data.overdue_count > 0 && (
              <Card variant="outlined" className="border-l-4 border-l-warning">
                <div className="flex items-center gap-3">
                  <Icon name="warning" size={24} className="text-warning flex-shrink-0" />
                  <div>
                    <p className="text-sm font-semibold text-on-surface">
                      {data.overdue_count} {data.overdue_count === 1 ? 'Vorgang' : 'Vorgänge'} überfällig
                    </p>
                    <p className="text-xs text-on-surface-variant">
                      Summe: {amountFmt.format(data.overdue_amount)}
                    </p>
                  </div>
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  )
}
