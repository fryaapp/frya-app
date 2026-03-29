interface StatusBlockData {
  status: 'loading' | 'success' | 'error' | 'pending'
  text: string
}

const spinnerKeyframes = `
@keyframes frya-spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
`

export function StatusBlock({ data }: { data: StatusBlockData }) {
  const isLoading = data.status === 'loading' || data.status === 'pending'

  const iconMap: Record<string, string> = {
    success: '\u2705',
    error: '\u274C',
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px 14px',
        gap: 10,
      }}
    >
      {isLoading && (
        <>
          <style>{spinnerKeyframes}</style>
          <div
            style={{
              width: 28,
              height: 28,
              border: '3px solid var(--frya-surface-container-high)',
              borderTopColor: 'var(--frya-primary)',
              borderRadius: '50%',
              animation: 'frya-spin 0.8s linear infinite',
            }}
          />
        </>
      )}

      {!isLoading && (
        <span style={{ fontSize: 24 }}>{iconMap[data.status] || '\u2139\uFE0F'}</span>
      )}

      <span
        style={{
          fontSize: 12,
          color: 'var(--frya-on-surface-variant)',
          fontFamily: 'Plus Jakarta Sans, sans-serif',
          textAlign: 'center',
        }}
      >
        {data.text}
      </span>
    </div>
  )
}
