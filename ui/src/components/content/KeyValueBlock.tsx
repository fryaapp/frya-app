interface KeyValueRow {
  key: string
  value: string | number
}

interface KeyValueBlockData {
  title?: string
  rows: KeyValueRow[]
}

function getValueColor(value: string | number): string | undefined {
  const str = String(value).trim()
  if (/^\+/.test(str) || /^[0-9]/.test(str)) {
    // Check if it looks like a positive monetary amount
    if (/^\+/.test(str)) return 'var(--frya-success)'
  }
  if (/^-/.test(str) || /^−/.test(str)) {
    return 'var(--frya-error)'
  }
  return undefined
}

export function KeyValueBlock({ data }: { data: KeyValueBlockData }) {
  return (
    <div
      style={{
        background: 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: '12px 14px',
      }}
    >
      {data.title && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            marginBottom: 8,
          }}
        >
          {data.title}
        </div>
      )}

      {data.rows.map((row, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '6px 0',
            fontSize: 12,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            borderBottom:
              i < data.rows.length - 1
                ? '1px solid var(--frya-outline-variant)'
                : 'none',
          }}
        >
          <span style={{ color: 'var(--frya-on-surface-variant)' }}>{row.key}</span>
          <span
            style={{
              fontWeight: 600,
              color: getValueColor(row.value) || 'var(--frya-on-surface)',
              fontFamily: 'Outfit, sans-serif',
            }}
          >
            {row.value}
          </span>
        </div>
      ))}
    </div>
  )
}
