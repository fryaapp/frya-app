interface ChartSeries {
  label: string
  value: number
  color: string
}

interface ChartBlockData {
  title?: string
  chart_type: 'donut' | 'bar' | 'line' | 'pie' | 'kpi'
  center_label?: string
  center_value?: string | number
  kpi_value?: string
  kpi_label?: string
  kpi_trend?: 'up' | 'down' | 'neutral'
  series: ChartSeries[]
}

export function ChartBlock({ data }: { data: ChartBlockData }) {
  if (data.chart_type === 'donut' || data.chart_type === 'pie') {
    return <DonutChart data={data} />
  }

  if (data.chart_type === 'kpi') {
    return <KpiChart data={data} />
  }

  if (data.chart_type === 'line') {
    return <LineChart data={data} />
  }

  // Fallback: bar chart
  return <BarChart data={data} />
}

function BarChart({ data }: { data: ChartBlockData }) {
  return (
    <div style={containerStyle}>
      {data.title && <div style={titleStyle}>{data.title}</div>}
      {(data?.series || []).map((s, i) => {
        const maxVal = Math.max(...(data?.series || []).map((x) => x.value))
        const pct = maxVal > 0 ? (s.value / maxVal) * 100 : 0
        return (
          <div key={i} style={{ marginBottom: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontFamily: 'Plus Jakarta Sans, sans-serif', marginBottom: 3 }}>
              <span style={{ color: 'var(--frya-on-surface-variant)' }}>{s.label}</span>
              <span style={{ color: 'var(--frya-on-surface)', fontWeight: 600, fontFamily: 'Outfit, sans-serif' }}>
                {typeof s.value === 'number' ? s.value.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' \u20ac' : s.value}
              </span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: 'var(--frya-surface-container-high)', overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct}%`, borderRadius: 3, background: s.color, transition: 'width 0.4s ease' }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function KpiChart({ data }: { data: ChartBlockData }) {
  const isPositive = data.kpi_trend === 'up'
  return (
    <div style={containerStyle}>
      {data.title && <div style={titleStyle}>{data.title}</div>}
      <div style={{ textAlign: 'center', padding: '12px 0' }}>
        <div style={{
          fontSize: 28, fontWeight: 700, fontFamily: 'Outfit, sans-serif',
          color: isPositive ? '#66E07A' : '#FF8A80',
          lineHeight: 1.2,
        }}>
          {data.kpi_trend === 'up' ? '\u25B2 ' : data.kpi_trend === 'down' ? '\u25BC ' : ''}{data.kpi_value}
        </div>
        {data.kpi_label && (
          <div style={{ fontSize: 11, color: 'var(--frya-on-surface-variant)', fontFamily: 'Plus Jakarta Sans, sans-serif', marginTop: 4 }}>
            {data.kpi_label}
          </div>
        )}
      </div>
      {/* Bar breakdown below KPI */}
      {(data?.series || []).length > 0 && (
        <div style={{ marginTop: 8 }}>
          {(data.series || []).map((s, i) => {
            const maxVal = Math.max(...(data?.series || []).map((x) => x.value))
            const pct = maxVal > 0 ? (s.value / maxVal) * 100 : 0
            return (
              <div key={i} style={{ marginBottom: 5 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'Plus Jakarta Sans, sans-serif', marginBottom: 2 }}>
                  <span style={{ color: 'var(--frya-on-surface-variant)' }}>{s.label}</span>
                  <span style={{ color: 'var(--frya-on-surface)', fontWeight: 600, fontFamily: 'Outfit, sans-serif' }}>
                    {s.value.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €'}
                  </span>
                </div>
                <div style={{ height: 5, borderRadius: 3, background: 'var(--frya-surface-container-high)', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${pct}%`, borderRadius: 3, background: s.color, transition: 'width 0.4s ease' }} />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function LineChart({ data }: { data: ChartBlockData }) {
  const series = data?.series || []
  if (series.length === 0) return null

  const maxVal = Math.max(...series.map((s) => s.value))
  const width = 340
  const height = 140
  const padding = { top: 10, right: 10, bottom: 25, left: 10 }
  const plotW = width - padding.left - padding.right
  const plotH = height - padding.top - padding.bottom
  const stepX = series.length > 1 ? plotW / (series.length - 1) : plotW

  const points = series.map((s, i) => ({
    x: padding.left + i * stepX,
    y: padding.top + plotH - (maxVal > 0 ? (s.value / maxVal) * plotH : 0),
    ...s,
  }))

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  const areaPath = linePath + ` L${points[points.length - 1].x},${padding.top + plotH} L${points[0].x},${padding.top + plotH} Z`

  return (
    <div style={containerStyle}>
      {data.title && <div style={titleStyle}>{data.title}</div>}
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((pct, i) => (
          <line key={i} x1={padding.left} x2={width - padding.right}
            y1={padding.top + plotH * (1 - pct)} y2={padding.top + plotH * (1 - pct)}
            stroke="var(--frya-surface-container-high)" strokeWidth={0.5} />
        ))}
        {/* Area fill */}
        <path d={areaPath} fill={series[0]?.color || '#F08A3A'} fillOpacity={0.15} />
        {/* Line */}
        <path d={linePath} fill="none" stroke={series[0]?.color || '#F08A3A'} strokeWidth={2} strokeLinejoin="round" />
        {/* Data points + labels */}
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={3} fill={p.color || '#F08A3A'} />
            <text x={p.x} y={height - 5} textAnchor="middle" fill="var(--frya-on-surface-variant)"
              fontSize={9} fontFamily="Plus Jakarta Sans, sans-serif">{p.label}</text>
            <text x={p.x} y={p.y - 8} textAnchor="middle" fill="var(--frya-on-surface)"
              fontSize={8} fontFamily="Outfit, sans-serif" fontWeight={600}>
              {p.value.toLocaleString('de-DE', { maximumFractionDigits: 0 })}
            </text>
          </g>
        ))}
      </svg>
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
    <div style={containerStyle}>
      {data.title && <div style={titleStyle}>{data.title}</div>}
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', position: 'relative', height: 140 }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--frya-surface-container-high)" strokeWidth={strokeWidth} />
          {segments.map((seg, i) => (
            <circle key={i} cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={seg.color} strokeWidth={strokeWidth}
              strokeDasharray={seg.dashArray} strokeDashoffset={seg.dashOffset} strokeLinecap="butt"
              style={{ transition: 'stroke-dasharray 0.4s ease, stroke-dashoffset 0.4s ease' }} />
          ))}
        </svg>
        {(data.center_value != null || data.center_label) && (
          <div style={{ position: 'absolute', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
            {data.center_value != null && (
              <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--frya-on-surface)', fontFamily: 'Outfit, sans-serif', lineHeight: 1.1 }}>
                {data.center_value}
              </div>
            )}
            {data.center_label && (
              <div style={{ fontSize: 9, color: 'var(--frya-on-surface-variant)', fontFamily: 'Plus Jakarta Sans, sans-serif', marginTop: 2 }}>
                {data.center_label}
              </div>
            )}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center', marginTop: 10 }}>
        {(data?.series || []).map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, fontFamily: 'Plus Jakarta Sans, sans-serif' }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
            <span style={{ color: 'var(--frya-on-surface-variant)' }}>{s.label}</span>
            <span style={{ color: 'var(--frya-on-surface)', fontWeight: 600, fontFamily: 'Outfit, sans-serif' }}>
              {typeof s.value === 'number' ? s.value.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : s.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

const containerStyle: React.CSSProperties = {
  background: 'var(--frya-surface-container-low)',
  borderRadius: 12,
  padding: 14,
}

const titleStyle: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: 'var(--frya-on-surface)',
  fontFamily: 'Plus Jakarta Sans, sans-serif',
  marginBottom: 10,
}
