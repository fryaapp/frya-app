interface TableBlockData {
  title?: string
  headers: string[]
  rows: Array<Array<string | number>>
}

export function TableBlock({ data }: { data: TableBlockData }) {
  return (
    <div
      style={{
        background: 'var(--frya-surface-container-low)',
        borderRadius: 12,
        overflow: 'hidden',
      }}
    >
      {data.title && (
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--frya-on-surface)',
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            padding: '12px 14px 8px',
          }}
        >
          {data.title}
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 11,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
          }}
        >
          <thead>
            <tr>
              {data.headers.map((header, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: 'left',
                    padding: '6px 14px',
                    fontSize: 10,
                    fontWeight: 600,
                    color: 'var(--frya-on-surface-variant)',
                    borderBottom: '1px solid var(--frya-outline-variant)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, ri) => (
              <tr
                key={ri}
                style={{
                  background:
                    ri % 2 === 1
                      ? 'var(--frya-surface-container)'
                      : 'transparent',
                }}
              >
                {row.map((cell, ci) => (
                  <td
                    key={ci}
                    style={{
                      padding: '6px 14px',
                      color: 'var(--frya-on-surface)',
                      whiteSpace: 'nowrap',
                      fontFamily:
                        typeof cell === 'number'
                          ? 'Outfit, sans-serif'
                          : 'Plus Jakarta Sans, sans-serif',
                      fontWeight: typeof cell === 'number' ? 500 : 400,
                    }}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
