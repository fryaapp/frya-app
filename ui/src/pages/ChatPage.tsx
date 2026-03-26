import { ChatPanel } from '../components/chat/ChatPanel'

/**
 * Standalone ChatPage — wraps ChatPanel for direct /chat route (unused in current layout).
 * The ChatPanel now lives inside SplitView via AppShell.
 */
export function ChatPage() {
  return (
    <div className="h-[calc(100vh-4rem)]">
      <ChatPanel />
    </div>
  )
}
