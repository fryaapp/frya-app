import { Outlet } from 'react-router-dom'
import { BottomNav } from './BottomNav'
import { SplitView } from './SplitView'
import { ChatPanel } from '../chat/ChatPanel'
import { StartPage } from '../../pages/StartPage'
import { Icon } from '../m3'

/**
 * AppShell — Main layout.
 * Manages SplitView (idle vs active), BottomNav, and BugReport FAB.
 */
export function AppShell() {
  return (
    <div className="flex flex-col h-screen bg-surface">
      {/* Main content area */}
      <main className="flex-1 pb-16 overflow-hidden">
        <SplitView
          idleContent={<StartPage />}
          contextContent={<Outlet />}
          chatContent={<ChatPanel />}
        />
      </main>

      {/* Bottom navigation */}
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
      className="fixed bottom-20 right-4 z-50 w-12 h-12 rounded-m3-lg bg-tertiary-container flex items-center justify-center shadow-md hover:opacity-90 transition-opacity"
      aria-label="Feedback senden"
    >
      <Icon name="bug_report" size={20} className="text-on-tertiary-container" />
    </button>
  )
}
