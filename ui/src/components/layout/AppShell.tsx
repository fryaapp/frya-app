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
      <main className="flex-1 pb-16 md:pb-0 overflow-hidden flex justify-center">
        <div className="w-full max-w-[720px]">
          <SplitView
            idleContent={<StartPage />}
            contextContent={<Outlet />}
            chatContent={<ChatPanel />}
          />
        </div>
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
      className="fixed bottom-[18px] right-[18px] z-[150] w-[34px] h-[34px] rounded-[12px] bg-surface-container-low border border-outline flex items-center justify-center hover:bg-error-container hover:border-error transition-all cursor-pointer group"
      aria-label="Feedback senden"
    >
      <Icon name="bug_report" size={15} className="text-on-surface-variant group-hover:text-error" />
    </button>
  )
}
