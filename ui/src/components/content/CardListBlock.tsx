import { CardBlock } from './CardBlock'
import { useFryaStore } from '../../stores/fryaStore'

interface CardListBlockData {
  title?: string
  items: Array<{
    title?: string
    subtitle?: string
    amount?: string | number
    badge?: { label: string; color: string }
    fields?: Array<{ key: string; value: string }>
    ai_label?: string
    case_id?: string
  }>
}

export function CardListBlock({ data }: { data: CardListBlockData }) {
  const send = useFryaStore((s) => s.send)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)

  const handleCardClick = (item: CardListBlockData['items'][0]) => {
    const name = item.title || 'Beleg'
    const msg = `Zeig mir ${name}`
    addUserMessage(msg)
    send({ text: msg })
  }

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
      {(data?.items || []).map((item, i) => (
        <div key={i} onClick={() => handleCardClick(item)} style={{ cursor: 'pointer' }}>
          <CardBlock data={item} />
        </div>
      ))}
    </div>
  )
}
