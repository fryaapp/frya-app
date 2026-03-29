import React from 'react'

interface ExportItem {
  label: string
  description?: string
  icon?: string
  format?: string
  action?: any
}

interface ExportBlockData {
  title?: string
  items: ExportItem[]
}

const formatIcons: Record<string, string> = {
  pdf: '\uD83D\uDCC4',
  csv: '\uD83D\uDCCA',
  xlsx: '\uD83D\uDCCA',
  zip: '\uD83D\uDCE6',
}

export function ExportBlock({
  data,
  onAction,
}: {
  data: ExportBlockData
  onAction?: (action: any) => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {data.title && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--frya-on-surface-variant)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            fontWeight: 500,
            paddingLeft: 2,
            marginBottom: 2,
          }}
        >
          {data.title}
        </div>
      )}
      {data.items.map((item, i) => (
        <ExportItemRow key={i} item={item} onAction={onAction} />
      ))}
    </div>
  )
}

function ExportItemRow({
  item,
  onAction,
}: {
  item: ExportItem
  onAction?: (action: any) => void
}) {
  const [hovered, setHovered] = React.useState(false)

  const icon = item.icon || formatIcons[item.format || ''] || '\uD83D\uDCC1'

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onAction?.(item.action || item)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: hovered
          ? 'var(--frya-surface-container)'
          : 'var(--frya-surface-container-low)',
        borderRadius: 10,
        padding: '10px 12px',
        cursor: 'pointer',
        transition: 'background 0.15s ease',
      }}
    >
      {/* Icon circle */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: 'var(--frya-primary-container)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 14,
          flexShrink: 0,
        }}
      >
        {icon}
      </div>

      {/* Text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
          }}
        >
          {item.label}
        </div>
        {item.description && (
          <div
            style={{
              fontSize: 10,
              color: 'var(--frya-on-surface-variant)',
              fontFamily: 'Plus Jakarta Sans, sans-serif',
              marginTop: 1,
            }}
          >
            {item.description}
          </div>
        )}
      </div>

      {/* Download arrow */}
      <svg
        width="16"
        height="16"
        viewBox="0 0 16 16"
        fill="none"
        style={{ flexShrink: 0, opacity: 0.5 }}
      >
        <path
          d="M8 3v7m0 0l-3-3m3 3l3-3M4 13h8"
          stroke="var(--frya-on-surface-variant)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  )
}
