import React from 'react'

interface DocumentBlockData {
  filename?: string
  title?: string
  size?: string
  url?: string
  mime_type?: string
  format?: string
  icon?: string
}

export function DocumentBlock({ data }: { data: DocumentBlockData }) {
  const [hovered, setHovered] = React.useState(false)
  const [downloading, setDownloading] = React.useState(false)

  // Support both 'filename' and 'title' (backend compat)
  const displayName = data.filename || data.title || 'Dokument'

  const isPdf =
    data.mime_type?.includes('pdf') ||
    data.format?.toLowerCase() === 'pdf' ||
    displayName.toLowerCase().endsWith('.pdf')

  /** Download file with auth token, then open as blob URL */
  const handleClick = async () => {
    if (!data.url || downloading) return

    // External URLs (https://) — open directly
    if (data.url.startsWith('http')) {
      window.open(data.url, '_blank')
      return
    }

    // Internal API URLs — fetch with auth token
    setDownloading(true)
    try {
      const token = localStorage.getItem('frya-token')
      const resp = await fetch(data.url, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!resp.ok) {
        console.error('Document download failed:', resp.status)
        // Fallback: open directly (might show auth error but better than nothing)
        window.open(data.url, '_blank')
        return
      }
      const blob = await resp.blob()
      const blobUrl = URL.createObjectURL(blob)
      window.open(blobUrl, '_blank')
      // Clean up blob URL after a delay
      setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000)
    } catch (err) {
      console.error('Document download error:', err)
      window.open(data.url, '_blank')
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        background: hovered
          ? 'var(--frya-surface-container)'
          : 'var(--frya-surface-container-low)',
        borderRadius: 12,
        padding: '10px 14px',
        transition: 'background 0.15s ease',
        cursor: data.url ? 'pointer' : 'default',
        opacity: downloading ? 0.6 : 1,
      }}
      onClick={handleClick}
    >
      {/* File icon */}
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 8,
          background: isPdf
            ? 'var(--frya-error-container)'
            : 'var(--frya-primary-container)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {data.icon ? (
          <span style={{ fontSize: 16 }}>{data.icon}</span>
        ) : (
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
            <path
              d="M5 2h5.5L14 5.5V14a2 2 0 01-2 2H5a2 2 0 01-2-2V4a2 2 0 012-2z"
              stroke={isPdf ? 'var(--frya-error)' : 'var(--frya-on-primary-container)'}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M10 2v4h4"
              stroke={isPdf ? 'var(--frya-error)' : 'var(--frya-on-primary-container)'}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {isPdf && (
              <text
                x="9"
                y="13"
                textAnchor="middle"
                fill="var(--frya-error)"
                fontSize="5"
                fontWeight="bold"
                fontFamily="Outfit, sans-serif"
              >
                PDF
              </text>
            )}
          </svg>
        )}
      </div>

      {/* Text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: "'Inter Variable', 'Inter', sans-serif",
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {downloading ? 'Wird geladen...' : displayName}
        </div>
        {data.size && !downloading && (
          <div
            style={{
              fontSize: 10,
              color: 'var(--frya-on-surface-variant)',
              fontFamily: "'Inter Variable', 'Inter', sans-serif",
              marginTop: 1,
            }}
          >
            {data.size}
          </div>
        )}
      </div>

      {/* Download indicator */}
      {data.url && (
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
      )}
    </div>
  )
}
