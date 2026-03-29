interface ProgressStat {
  value: string | number
  label: string
}

interface ProgressBlockData {
  title?: string
  progress: number // 0-100
  stats?: ProgressStat[]
}

export function ProgressBlock({ data }: { data: ProgressBlockData }) {
  const pct = Math.max(0, Math.min(100, data.progress))

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
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 8,
          }}
        >
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--frya-on-surface)',
              fontFamily: 'Plus Jakarta Sans, sans-serif',
            }}
          >
            {data.title}
          </span>
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: 'var(--frya-primary)',
              fontFamily: 'Outfit, sans-serif',
            }}
          >
            {pct}%
          </span>
        </div>
      )}

      {/* Progress bar */}
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: 'var(--frya-surface-container-high)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${pct}%`,
            borderRadius: 3,
            background: 'var(--frya-primary)',
            transition: 'width 0.4s ease',
          }}
        />
      </div>

      {/* Stats grid */}
      {data.stats && data.stats.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `repeat(${Math.min(data.stats.length, 3)}, 1fr)`,
            gap: 8,
            marginTop: 12,
          }}
        >
          {data.stats.map((stat, i) => (
            <div key={i} style={{ textAlign: 'center' }}>
              <div
                style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: 'var(--frya-on-surface)',
                  fontFamily: 'Outfit, sans-serif',
                  lineHeight: 1.2,
                }}
              >
                {stat.value}
              </div>
              <div
                style={{
                  fontSize: 9,
                  color: 'var(--frya-on-surface-variant)',
                  fontFamily: 'Plus Jakarta Sans, sans-serif',
                  marginTop: 2,
                }}
              >
                {stat.label}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
