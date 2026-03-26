import type { ChatMessage } from '../../stores/chatStore'
import { ApprovalCard } from './ApprovalCard'
import { DuplicateCard } from './DuplicateCard'
import { NotificationBubble } from './NotificationBubble'

interface ChatBubbleProps {
  message: ChatMessage
  onApprovalAction: (messageId: string, action: string) => void
}

export function ChatBubble({ message, onApprovalAction }: ChatBubbleProps) {
  // System messages: approval, duplicate, notification
  if (message.role === 'system') {
    if (message.approval) {
      return (
        <ApprovalCard
          data={message.approval}
          messageId={message.id}
          resolvedAction={message.approvalAction}
          onResolved={onApprovalAction}
        />
      )
    }
    if (message.duplicate) {
      return <DuplicateCard data={message.duplicate} />
    }
    if (message.notificationType) {
      return <NotificationBubble text={message.text} notificationType={message.notificationType} />
    }
    return null
  }

  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center mr-2 shrink-0 self-end">
          <span className="text-xs font-bold text-on-primary-container">F</span>
        </div>
      )}
      <div
        className={`max-w-[80%] px-4 py-3 rounded-m3-lg text-sm leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-primary text-on-primary rounded-br-sm'
            : 'bg-surface-container-high text-on-surface rounded-bl-sm'
        }`}
      >
        {message.text || (message.isStreaming ? '' : '')}
        {message.isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-current ml-0.5 animate-pulse align-text-bottom" />
        )}
      </div>
    </div>
  )
}
