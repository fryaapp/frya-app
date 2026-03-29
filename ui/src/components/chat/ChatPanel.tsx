import { useEffect, useRef, useCallback } from 'react'
import { useChatStore } from '../../stores/chatStore'
import { useUiStore } from '../../stores/uiStore'
import { useWebSocket, type WsMessage } from '../../hooks/useWebSocket'
import { ChatBubble } from './ChatBubble'
import { ChatInput } from './ChatInput'
import { TypingIndicator } from './TypingIndicator'
import { SuggestionChips } from './SuggestionChips'

/**
 * ChatPanel — lives in the bottom 42% of the split view.
 * Also used full-height when no context panel is active.
 */
export function ChatPanel() {
  const {
    messages, isTyping, typingHint,
    addUserMessage, startAssistantMessage, appendChunk,
    completeMessage, setTyping, addApprovalRequest,
    addNotification, addDuplicate, setApprovalAction,
  } = useChatStore()

  const { openSplit } = useUiStore()
  const streamIdRef = useRef<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const handleWsMessage = useCallback((msg: WsMessage) => {
    switch (msg.type) {
      case 'typing':
        setTyping(msg.active, msg.hint)
        // Don't create streamIdRef here — let TypingIndicator show until chunks arrive
        break

      case 'chunk':
        if (!streamIdRef.current) {
          streamIdRef.current = startAssistantMessage()
        }
        appendChunk(streamIdRef.current, msg.text)
        break

      case 'message_complete': {
        // If no streaming message exists (e.g. REST fallback), create one
        if (!streamIdRef.current) {
          streamIdRef.current = startAssistantMessage()
        }
        completeMessage(streamIdRef.current, msg.text, msg.suggestions, msg.case_ref, msg.context_type)
      }
        // If context_type is present, open the split with that context
        if (msg.context_type && msg.context_type !== 'none') {
          openSplit(msg.context_type as Parameters<typeof openSplit>[0])
        }
        streamIdRef.current = null
        setTyping(false)
        break

      case 'approval_request':
        addApprovalRequest({
          case_id: msg.case_id,
          case_number: msg.case_number,
          vendor: msg.vendor,
          amount: msg.amount,
          currency: msg.currency,
          document_type: msg.document_type,
          buttons: msg.buttons,
        })
        break

      case 'notification':
        addNotification(msg.text, msg.notification_type)
        break

      case 'duplicate':
        addDuplicate({ original_title: msg.original_title, paperless_id: msg.paperless_id })
        break

      case 'ui_hint':
        if (msg.action === 'open_context' && msg.context_type) {
          openSplit(msg.context_type as Parameters<typeof openSplit>[0])
        } else if (msg.action === 'close_context') {
          useUiStore.getState().closeSplit()
        }
        break

      case 'error':
        if (streamIdRef.current) {
          completeMessage(streamIdRef.current, `Fehler: ${msg.message}`)
        } else {
          addNotification(msg.message, 'error')
        }
        streamIdRef.current = null
        setTyping(false)
        break
    }
  }, [setTyping, startAssistantMessage, appendChunk, completeMessage, addApprovalRequest, addNotification, addDuplicate, openSplit])

  const { send, connected } = useWebSocket(handleWsMessage)

  // Drain pending message queued by StartPage (which doesn't have WS access)
  const pendingSend = useChatStore((s) => s.pendingSend)
  useEffect(() => {
    if (pendingSend && connected) {
      send(pendingSend)
      useChatStore.getState().setPendingSend(null)
    }
  }, [pendingSend, connected, send])

  const handleSend = useCallback((text: string) => {
    addUserMessage(text)
    send(text)
    // If not in split mode yet, open it (chat becomes active)
    if (!useUiStore.getState().splitOpen) {
      openSplit('none')
    }
  }, [addUserMessage, send, openSplit])

  const handleFileUploaded = useCallback(() => {
    addNotification('Datei wird hochgeladen und analysiert…', 'analysis')
  }, [addNotification])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    // Only auto-scroll if user is near bottom
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100
    if (isNearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [messages, isTyping])

  // Last message suggestions
  const lastMsg = messages[messages.length - 1]
  const suggestions = lastMsg?.role === 'frya' && !lastMsg.isStreaming ? lastMsg.suggestions || [] : []

  return (
    <div className="flex flex-col h-full">
      {/* Connection status */}
      {!connected && (
        <div className="px-4 py-1.5 bg-warning-container/50 text-center">
          <span className="text-xs text-warning">Verbindung wird hergestellt…</span>
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4">

        {/* Older messages fade — show opacity gradient on first few visible */}
        {messages.map((m, i) => {
          const fromEnd = messages.length - i
          const opacity = fromEnd > 8 ? 'opacity-40' : fromEnd > 5 ? 'opacity-70' : ''
          return (
            <div key={m.id} className={opacity}>
              <ChatBubble message={m} onApprovalAction={setApprovalAction} />
            </div>
          )
        })}
        {isTyping && !streamIdRef.current && <TypingIndicator hint={typingHint} />}
      </div>

      {/* Suggestions */}
      <SuggestionChips suggestions={suggestions} onSelect={handleSend} />

      {/* Input */}
      <div className="px-3 pb-3 pt-1">
        <ChatInput
          onSend={handleSend}
          onFileUploaded={handleFileUploaded}
          disabled={!connected}
        />
      </div>
    </div>
  )
}
