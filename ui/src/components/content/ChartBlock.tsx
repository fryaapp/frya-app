interface ChartSeries {
  label: string
  value: number
  color: string
}

interface ChartBlockData {
  title?: string
  chart_type: 'donut' | 'bar' | 'line'
  center_label?: string
  center_value?: string | number
  series: ChartSeries[]
}

export function ChartBlock({ data }: { data: ChartBlockData }) {
  if (data.chart_type === 'donut') {
    return <DonutChart data={data} />
  }

  // Fallback: render a simple bar representation for other chart types
  return (
    <div
      style={{
        background: 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: 14,
      }}
    >
      {data.title && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            marginBottom: 10,
          }}
        >
          {data.title}
        </div>
      )}
      {(data?.series || []).map((s, i) => {
        const maxVal = Math.max(...(data?.series || []).map((x) => x.value))
        const pct = maxVal > 0 ? (s.value / maxVal) * 100 : 0
        return (
          <div key={i} style={{ marginBottom: 6 }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 11,
                fontFamily: 'Plus Jakarta Sans, sans-serif',
                marginBottom: 3,
              }}
            >
              <span style={{ color: 'var(--frya-on-surface-variant)' }}>{s.label}</span>
              <span
                style={{
                  color: 'var(--frya-on-surface)',
                  fontWeight: 600,
                  fontFamily: 'Outfit, sans-serif',
                }}
              >
                {s.value}
              </span>
            </div>
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
                  background: s.color,
                  transition: 'width 0.4s ease',
                }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DonutChart({ data }: { data: ChartBlockData }) {
  const total = (data?.series || []).reduce((sum, s) => sum + s.value, 0)
  const size = 120
  const strokeWidth = 18
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius

  let accumulated = 0
  const segments = (data?.series || []).map((s) => {
    const pct = total > 0 ? s.value / total : 0
    const dashArray = `${pct * circumference} ${circumference}`
    const dashOffset = -accumulated * circumference
    accumulated += pct
    return { ...s, dashArray, dashOffset }
  })

  return (
    <div
      style={{
        background: 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: 14,
      }}
    >
      {data.title && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            marginBottom: 10,
          }}
        >
          {data.title}
        </div>
      )}

      {/* Donut SVG */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          position: 'relative',
          height: 140,
        }}
      >
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          style={{ transform: 'rotate(-90deg)' }}
        >
          {/* Background circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--frya-surface-container-high)"
            strokeWidth={strokeWidth}
          />
          {/* Data segments */}
          {segments.map((seg, i) => (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth={strokeWidth}
              strokeDasharray={seg.dashArray}
              strokeDashoffset={seg.dashOffset}
              strokeLinecap="butt"
              style={{ transition: 'stroke-dasharray 0.4s ease, stroke-dashoffset 0.4s ease' }}
            />
          ))}
        </svg>

        {/* Center text */}
        {(data.center_value != null || data.center_label) && (
          <div
            style={{
              position: 'absolute',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {data.center_value != null && (
              <div
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: 'var(--frya-on-surface)',
                  fontFamily: 'Outfit, sans-serif',
                  lineHeight: 1.1,
                }}
              >
                {data.center_value}
              </div>
            )}
            {data.center_label && (
              <div
                style={{
                  fontSize: 9,
                  color: 'var(--frya-on-surface-variant)',
                  fontFamily: 'Plus Jakarta Sans, sans-serif',
                  marginTop: 2,
                }}
              >
                {data.center_label}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 10,
          justifyContent: 'center',
          marginTop: 10,
        }}
      >
        {(data?.series || []).map((s, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              fontSize: 10,
              fontFamily: 'Plus Jakarta Sans, sans-serif',
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: s.color,
                flexShrink: 0,
              }}
            />
            <span style={{ color: 'var(--frya-on-surface-variant)' }}>{s.label}</span>
            <span
              style={{
                color: 'var(--frya-on-surface)',
                fontWeight: 600,
                fontFamily: 'Outfit, sans-serif',
              }}
            >
              {s.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
