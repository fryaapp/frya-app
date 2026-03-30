import { useEffect, useRef } from 'react'
import { useFryaStore } from '../../stores/fryaStore'
import { ChatMessage } from './ChatMessage'
import { TypingIndicator } from './TypingIndicator'

export function ChatHistory() {
  const messages = useFryaStore((s) => s.messages)
  const isTyping = useFryaStore((s) => s.isTyping)
  const typingHint = useFryaStore((s) => s.typingHint)
  const sendAction = useFryaStore((s) => s.sendAction)
  const submitForm = useFryaStore((s) => s.submitForm)
  const scrollRef = useRef<HTMLDivElement>(null)

  const prevCountRef = useRef(0)

  // Auto-scroll: ALWAYS on new user messages, near-bottom for frya messages
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const prevCount = prevCountRef.current
    prevCountRef.current = messages.length

    // New message added → ALWAYS scroll to bottom
    if (messages.length > prevCount) {
      requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }))
      return
    }

    // Typing indicator → scroll if near bottom
    if (isTyping) {
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200
      if (isNearBottom) {
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
      }
    }
  }, [messages, isTyping])

  const handleAction = (action: any) => {
    sendAction(action)
  }

  const handleSubmit = (formType: string, formData: Record<string, any>) => {
    submitForm('', formType, formData)
  }

  return (
    <div
      ref={scrollRef}
      style={{
        flex: 1,
        minHeight: 0,
        overflowY: 'auto',
        padding: '16px 20px',
        maxWidth: 720,
        width: '100%',
        margin: '0 auto',
        boxSizing: 'border-box',
      }}
      className="frya-chat-scroll"
    >
      {messages.map((m) => (
        <ChatMessage
          key={m.id}
          message={m}
          onAction={handleAction}
          onSubmit={handleSubmit}
        />
      ))}

      {isTyping && <TypingIndicator hint={typingHint} />}

      <style>{`
        .frya-chat-scroll::-webkit-scrollbar {
          width: 4px;
        }
        .frya-chat-scroll::-webkit-scrollbar-track {
          background: transparent;
        }
        .frya-chat-scroll::-webkit-scrollbar-thumb {
          background: var(--frya-outline-variant);
          border-radius: 2px;
        }
        .frya-chat-scroll {
          scrollbar-width: thin;
          scrollbar-color: var(--frya-outline-variant) transparent;
        }
      `}</style>
    </div>
  )
}
