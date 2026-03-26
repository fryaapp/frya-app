import { useEffect, useState } from 'react'
import { Icon, Card, Chip } from '../components/m3'
import { ChatInput } from '../components/chat'
import { useUiStore, type ContextType } from '../stores/uiStore'
import { useChatStore } from '../stores/chatStore'
import { api } from '../lib/api'

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface InboxItem {
  id: string
  vendor_name?: string
  amount?: number
  created_at?: string
  status?: string
}

interface InboxResponse {
  count: number
  items: InboxItem[]
}

interface FinanceSummary {
  period: string
  income: number
  expenses: number
  open_receivables: number
  open_payables: number
  overdue_count: number
  overdue_amount: number
}

interface DeadlinesResponse {
  overdue: unknown[]
  due_today: unknown[]
  due_soon: unknown[]
  skonto_expiring: unknown[]
  summary: string
}

interface DashboardData {
  inbox: InboxResponse
  finance: FinanceSummary
  deadlines: DeadlinesResponse
  loading: boolean
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const EUR = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' })

const shortcuts: { label: string; icon: string; context: ContextType }[] = [
  { label: 'Inbox', icon: 'inbox', context: 'inbox' },
  { label: 'Fristen', icon: 'event', context: 'deadlines' },
  { label: 'Vorgänge', icon: 'folder_open', context: 'cases' },
]

const EMPTY_INBOX: InboxResponse = { count: 0, items: [] }
const EMPTY_FINANCE: FinanceSummary = {
  period: '', income: 0, expenses: 0,
  open_receivables: 0, open_payables: 0, overdue_count: 0, overdue_amount: 0,
}
const EMPTY_DEADLINES: DeadlinesResponse = {
  overdue: [], due_today: [], due_soon: [], skonto_expiring: [], summary: '',
}

/* ------------------------------------------------------------------ */
/*  Skeleton                                                           */
/* ------------------------------------------------------------------ */

function KpiSkeleton() {
  return (
    <Card variant="outlined" className="animate-pulse">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-surface-container-high" />
        <div className="flex-1">
          <div className="h-3 w-16 bg-surface-container-high rounded mb-2" />
          <div className="h-5 w-12 bg-surface-container-high rounded" />
        </div>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  KPI Card                                                           */
/* ------------------------------------------------------------------ */

interface KpiCardProps {
  icon: string
  label: string
  value: string
  iconColor?: string
  onClick?: () => void
}

function KpiCard({ icon, label, value, iconColor = 'text-on-surface-variant', onClick }: KpiCardProps) {
  return (
    <Card variant="outlined" className="min-w-0" onClick={onClick}>
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-full bg-surface-container-high flex items-center justify-center shrink-0">
          <Icon name={icon} size={20} className={iconColor} />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-on-surface-variant truncate">{label}</p>
          <p className="text-base font-semibold text-on-surface truncate">{value}</p>
        </div>
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/*  StartPage                                                          */
/* ------------------------------------------------------------------ */

/**
 * StartPage — Dashboard-Startseite.
 * Kompakter Frya-Avatar + Begrüßung, KPI-Karten, letzte Belege,
 * Shortcut-Chips und Eingabefeld.
 */
export function StartPage() {
  const openSplit = useUiStore((s) => s.openSplit)

  const [data, setData] = useState<DashboardData>({
    inbox: EMPTY_INBOX,
    finance: EMPTY_FINANCE,
    deadlines: EMPTY_DEADLINES,
    loading: true,
  })

  // ---- Fetch all KPI data in parallel ----
  useEffect(() => {
    let cancelled = false

    async function load() {
      const [inbox, finance, deadlines] = await Promise.all([
        api.get<InboxResponse>('/inbox?status=pending&limit=5').catch(() => EMPTY_INBOX),
        api.get<FinanceSummary>('/finance/summary?period=month').catch(() => EMPTY_FINANCE),
        api.get<DeadlinesResponse>('/deadlines').catch(() => EMPTY_DEADLINES),
      ])

      if (!cancelled) {
        setData({ inbox, finance, deadlines, loading: false })
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  // ---- Greeting ----
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Guten Morgen' : hour < 18 ? 'Hallo' : 'Guten Abend'

  // ---- Handlers ----
  const handleSend = (text: string) => {
    useChatStore.getState().addUserMessage(text)
    openSplit('none')
  }

  const handleUpload = () => openSplit('upload_status')

  const overdueCount = data.deadlines.overdue.length

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto px-4 pt-6 pb-2">
        {/* ---- Compact avatar + greeting ---- */}
        <div className="flex items-center gap-3 mb-5">
          <div className="w-12 h-12 rounded-full bg-primary-container flex items-center justify-center shadow-md shrink-0">
            <span className="text-xl font-display font-bold text-on-primary-container">F</span>
          </div>
          <div>
            <h1 className="text-lg font-display font-bold text-on-surface leading-tight">
              {greeting}!
            </h1>
            <p className="text-sm text-on-surface-variant">Was kann ich für dich tun?</p>
          </div>
        </div>

        {/* ---- KPI Grid 2x2 ---- */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          {data.loading ? (
            <>
              <KpiSkeleton />
              <KpiSkeleton />
              <KpiSkeleton />
              <KpiSkeleton />
            </>
          ) : (
            <>
              <KpiCard
                icon="inbox"
                label="Offene Belege"
                value={String(data.inbox.count)}
                onClick={() => openSplit('inbox')}
              />
              <KpiCard
                icon="trending_up"
                label="Einnahmen"
                value={EUR.format(data.finance.income)}
                iconColor="text-success"
              />
              <KpiCard
                icon="trending_down"
                label="Ausgaben"
                value={EUR.format(data.finance.expenses)}
                iconColor="text-error"
              />
              <KpiCard
                icon="warning"
                label="Überfällige Fristen"
                value={String(overdueCount)}
                iconColor={overdueCount > 0 ? 'text-error' : 'text-on-surface-variant'}
                onClick={() => openSplit('deadlines')}
              />
            </>
          )}
        </div>

        {/* ---- Letzte Belege ---- */}
        {!data.loading && data.inbox.items.length > 0 && (
          <div className="mb-5">
            <h2 className="text-sm font-semibold text-on-surface mb-2">Letzte Belege</h2>
            <Card variant="outlined" className="divide-y divide-outline-variant">
              {data.inbox.items.slice(0, 5).map((item) => (
                <div key={item.id} className="flex items-center justify-between py-2.5 first:pt-0 last:pb-0">
                  <span className="text-sm text-on-surface truncate mr-2">
                    {item.vendor_name || 'Unbekannt'}
                  </span>
                  {item.amount != null && (
                    <span className="text-sm font-medium text-on-surface whitespace-nowrap">
                      {EUR.format(item.amount)}
                    </span>
                  )}
                </div>
              ))}
            </Card>
          </div>
        )}

        {/* ---- Shortcut chips ---- */}
        <div className="flex flex-wrap gap-2 mb-4">
          {shortcuts.map((s) => (
            <Chip
              key={s.context}
              label={s.label}
              icon={s.icon}
              color="primary"
              onClick={() => openSplit(s.context)}
            />
          ))}
        </div>

        {/* ---- FAB: Beleg hochladen ---- */}
        <button
          onClick={handleUpload}
          className="fixed right-5 bottom-24 z-10 w-14 h-14 rounded-2xl bg-primary text-on-primary shadow-lg flex items-center justify-center hover:shadow-xl active:scale-95 transition-all"
          aria-label="Beleg hochladen"
        >
          <Icon name="upload_file" size={24} />
        </button>
      </div>

      {/* ---- Chat input at bottom ---- */}
      <ChatInput
        onSend={handleSend}
        placeholder="Nachricht an Frya\u2026"
      />
    </div>
  )
}
