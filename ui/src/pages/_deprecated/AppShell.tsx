import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { BottomNav } from './BottomNav'
import { IconRail } from './IconRail'
import { SplitView } from './SplitView'
import { ChatPanel } from '../chat/ChatPanel'
import { StartPage } from '../../pages/StartPage'
import { BugReportFAB } from './BugReportOverlay'
import { useUiStore, type ContextType } from '../../stores/uiStore'

/** Map route paths to context types so direct URL navigation opens the split */
const ROUTE_CONTEXT: Record<string, ContextType> = {
  '/inbox': 'inbox',
  '/cases': 'cases',
  '/finance': 'finance',
  '/deadlines': 'deadlines',
  '/upload': 'upload_status',
  '/settings': 'settings',
  // '/feedback' is now handled by global BugReportOverlay, not a route
  '/documents': 'documents',
  '/profile': 'profile',
  '/legal': 'legal',
}

/**
 * AppShell — Main layout.
 * Manages IconRail (desktop), SplitView (idle vs active), BottomNav (mobile), and BugReport FAB.
 */
export function AppShell() {
  const location = useLocation()
  const openSplit = useUiStore((s) => s.openSplit)

  // Sync route → SplitView state (handles direct URL navigation + browser back/forward)
  // Only OPENS the split for context routes — never closes it (chat may be active on /)
  useEffect(() => {
    const path = location.pathname
    // Check exact match first, then prefix match for nested routes like /cases/123
    const ctx = ROUTE_CONTEXT[path] ??
      Object.entries(ROUTE_CONTEXT).find(([p]) => p !== '/' && path.startsWith(p))?.[1]
    if (ctx) {
      openSplit(ctx)
    }
    // Don't closeSplit on / — the Home button in IconRail handles that explicitly
  }, [location.pathname, openSplit])

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
