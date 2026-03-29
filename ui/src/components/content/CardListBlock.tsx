import { CardBlock } from './CardBlock'

interface CardListBlockData {
  title?: string
  items: Array<{
    title?: string
    subtitle?: string
    amount?: string | number
    badge?: { label: string; color: string }
    fields?: Array<{ key: string; value: string }>
    ai_label?: string
  }>
}

export function CardListBlock({ data }: { data: CardListBlockData }) {
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
          }}
        >
          {data.title}
        </div>
      )}
      {data.items.map((item, i) => (
        <CardBlock key={i} data={item} />
      ))}
    </div>
  )
}
