import React from 'react'

interface CardBadge {
  label: string
  color: 'success' | 'info' | 'warning' | 'error' | string
}

interface CardField {
  key: string
  value: string
}

interface CardBlockData {
  title?: string
  subtitle?: string
  amount?: string | number
  badge?: CardBadge
  fields?: CardField[]
  ai_label?: string
}

export function CardBlock({ data }: { data: CardBlockData }) {
  const [hovered, setHovered] = React.useState(false)

  const badgeColorMap: Record<string, { bg: string; fg: string }> = {
    success: { bg: 'var(--frya-success-container)', fg: 'var(--frya-success)' },
    info: { bg: 'var(--frya-info-container)', fg: 'var(--frya-info)' },
    warning: { bg: 'var(--frya-warning-container)', fg: 'var(--frya-warning)' },
    error: { bg: 'var(--frya-error-container)', fg: 'var(--frya-error)' },
  }

  const badge = data.badge
  const badgeColors = badge ? badgeColorMap[badge.color] || badgeColorMap.info : null

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: hovered
          ? 'var(--frya-surface-container)'
          : 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: '12px 14px',
        transition: 'background 0.15s ease',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {data.title && (
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: 'var(--frya-on-surface)',
                fontFamily: 'Plus Jakarta Sans, sans-serif',
                lineHeight: 1.3,
              }}
            >
              {data.title}
            </div>
          )}
          {data.subtitle && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--frya-on-surface-variant)',
                fontFamily: 'Plus Jakarta Sans, sans-serif',
                marginTop: 2,
                lineHeight: 1.3,
              }}
            >
              {data.subtitle}
            </div>
          )}
        </div>

        {data.amount != null && (
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: 'var(--frya-on-surface)',
              fontFamily: 'Outfit, sans-serif',
              whiteSpace: 'nowrap',
            }}
          >
            {data.amount}
          </div>
        )}
      </div>

      {/* Badge */}
      {badge && badgeColors && (
        <div
          style={{
            display: 'inline-block',
            marginTop: 8,
            padding: '2px 8px',
            borderRadius: 6,
            fontSize: 10,
            fontWeight: 600,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            background: badgeColors.bg,
            color: badgeColors.fg,
          }}
        >
          {badge.label}
        </div>
      )}

      {/* Fields */}
      {data.fields && data.fields.length > 0 && (
        <div style={{ marginTop: 8 }}>
          {data.fields.map((field, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '4px 0',
                fontSize: 11,
                fontFamily: 'Plus Jakarta Sans, sans-serif',
                borderBottom:
                  i < data.fields!.length - 1
                    ? '1px solid var(--frya-outline-variant)'
                    : 'none',
              }}
            >
              <span style={{ color: 'var(--frya-on-surface-variant)' }}>{field.key}</span>
              <span style={{ color: 'var(--frya-on-surface)', fontWeight: 500 }}>
                {field.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* AI label */}
      {data.ai_label && (
        <div
          style={{
            marginTop: 8,
            fontSize: 10,
            color: 'var(--frya-primary)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            fontStyle: 'italic',
          }}
        >
          {data.ai_label}
        </div>
      )}
    </div>
  )
}
