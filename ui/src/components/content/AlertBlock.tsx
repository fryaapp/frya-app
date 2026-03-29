interface AlertBlockData {
  severity: 'info' | 'warning' | 'error' | 'success'
  text: string
  icon?: string
}

const severityMap: Record<
  string,
  { bg: string; fg: string; defaultIcon: string }
> = {
  info: {
    bg: 'var(--frya-info-container)',
    fg: 'var(--frya-info)',
    defaultIcon: '\u2139\uFE0F',
  },
  warning: {
    bg: 'var(--frya-warning-container)',
    fg: 'var(--frya-warning)',
    defaultIcon: '\u26A0\uFE0F',
  },
  error: {
    bg: 'var(--frya-error-container)',
    fg: 'var(--frya-error)',
    defaultIcon: '\u274C',
  },
  success: {
    bg: 'var(--frya-success-container)',
    fg: 'var(--frya-success)',
    defaultIcon: '\u2705',
  },
}

export function AlertBlock({ data }: { data: AlertBlockData }) {
  const colors = severityMap[data.severity] || severityMap.info

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        background: colors.bg,
        borderRadius: 12,
        padding: '10px 14px',
      }}
    >
      <span style={{ fontSize: 14, flexShrink: 0, lineHeight: 1.4 }}>
        {data.icon || colors.defaultIcon}
      </span>
      <span
        style={{
          fontSize: 12,
          color: colors.fg,
          fontFamily: 'Plus Jakarta Sans, sans-serif',
          lineHeight: 1.5,
        }}
      >
        {data.text}
      </span>
    </div>
  )
}
