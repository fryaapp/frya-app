interface TypingIndicatorProps {
  hint?: string | null
}

export function TypingIndicator({ hint }: TypingIndicatorProps) {
  return (
    <div className="flex justify-start mb-3">
      <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center mr-2 shrink-0 self-end">
        <span className="text-xs font-bold text-on-primary-container">F</span>
      </div>
      <div className="bg-surface-container-high rounded-m3-lg px-4 py-3">
        {hint ? (
          <p className="text-xs text-on-surface-variant italic">{hint}</p>
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 bg-on-surface-variant/50 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-2 h-2 bg-on-surface-variant/50 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-2 h-2 bg-on-surface-variant/50 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        )}
      </div>
    </div>
  )
}
