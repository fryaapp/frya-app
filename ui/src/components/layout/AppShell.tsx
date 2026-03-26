import { Outlet } from 'react-router-dom'
import { BottomNav } from './BottomNav'
import { IconRail } from './IconRail'
import { SplitView } from './SplitView'
import { ChatPanel } from '../chat/ChatPanel'
import { StartPage } from '../../pages/StartPage'
import { Icon } from '../m3'

/**
 * AppShell — Main layout.
 * Manages IconRail (desktop), SplitView (idle vs active), BottomNav (mobile), and BugReport FAB.
 */
export function AppShell() {
  return (
    <div className="flex h-screen bg-surface">
      {/* Desktop icon rail — visible on md+ */}
      <IconRail className="hidden md:flex" />

      {/* Main content area */}
      <main className="flex-1 pb-16 md:pb-0 overflow-hidden">
        <SplitView
          idleContent={<StartPage />}
          contextContent={<Outlet />}
          chatContent={<ChatPanel />}
        />
      </main>

      {/* Bottom navigation — mobile only */}
      <BottomNav />

      {/* Bug report FAB */}
      <BugReportFAB />
    </div>
  )
}

function BugReportFAB() {
  return (
    <button
      onClick={() => window.open('/feedback', '_self')}
      className="fixed bottom-3 right-3 z-50 w-[30px] h-[30px] rounded-[10px] bg-surface-container-low border border-outline-variant flex items-center justify-center hover:bg-error-container hover:border-error hover:text-error transition-colors"
      aria-label="Feedback senden"
    >
      <Icon name="bug_report" size={14} className="text-on-surface-variant" />
    </button>
  )
}
