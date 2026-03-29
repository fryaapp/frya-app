import { Icon } from '../components/m3'

export function NotificationsPage() {
  return (
    <div className="flex flex-col h-full bg-surface">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 bg-surface-container">
        <Icon name="notifications" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Benachrichtigungen</h1>
      </div>

      {/* Empty state */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="flex flex-col items-center justify-center gap-4 py-16">
          <Icon name="check_circle" size={56} className="text-success" />
          <p className="text-base font-semibold text-on-surface text-center">
            Keine neuen Benachrichtigungen.
          </p>
          <p className="text-sm text-on-surface-variant text-center max-w-xs">
            Benachrichtigungen werden in einer zuk&uuml;nftigen Version verf&uuml;gbar sein.
          </p>
        </div>
      </div>
    </div>
  )
}
