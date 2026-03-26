import ReactMarkdown from 'react-markdown'
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
        className={`max-w-[80%] px-4 py-3 rounded-m3-lg text-sm leading-relaxed ${
          isUser
            ? 'bg-primary text-on-primary rounded-br-sm whitespace-pre-wrap'
            : 'bg-surface-container-high text-on-surface rounded-bl-sm'
        }`}
      >
        {isUser ? (
          message.text
        ) : (
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-1.5 last:mb-0">{children}</p>,
              strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
              ul: ({ children }) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-4 mb-1.5 space-y-0.5">{children}</ol>,
              li: ({ children }) => <li>{children}</li>,
              code: ({ node, className, children, ...props }) => {
                const isBlock = className?.includes('language-')
                return isBlock ? (
                  <code className="block bg-surface-container px-3 py-2 rounded-lg text-xs font-mono my-1.5 overflow-x-auto whitespace-pre" {...props}>
                    {children}
                  </code>
                ) : (
                  <code className="bg-surface-container px-1 py-0.5 rounded text-xs font-mono" {...props}>
                    {children}
                  </code>
                )
              },
              pre: ({ children }) => <pre className="my-1.5">{children}</pre>,
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline">
                  {children}
                </a>
              ),
              table: ({ children }) => (
                <div className="overflow-x-auto my-1.5">
                  <table className="min-w-full border-collapse text-xs">{children}</table>
                </div>
              ),
              thead: ({ children }) => <thead className="bg-surface-container">{children}</thead>,
              th: ({ children }) => <th className="border border-outline-variant px-2 py-1 text-left font-semibold">{children}</th>,
              td: ({ children }) => <td className="border border-outline-variant px-2 py-1">{children}</td>,
              h1: ({ children }) => <h1 className="text-base font-bold mb-1">{children}</h1>,
              h2: ({ children }) => <h2 className="text-sm font-bold mb-1">{children}</h2>,
              h3: ({ children }) => <h3 className="text-sm font-semibold mb-1">{children}</h3>,
              blockquote: ({ children }) => (
                <blockquote className="border-l-2 border-outline-variant pl-3 my-1.5 opacity-80">{children}</blockquote>
              ),
              hr: () => <hr className="border-outline-variant my-2" />,
            }}
          >
            {message.text || ''}
          </ReactMarkdown>
        )}
        {message.isStreaming && (
          <span className="inline-block w-1.5 h-4 bg-current ml-0.5 animate-pulse align-text-bottom" />
        )}
      </div>
    </div>
  )
}
