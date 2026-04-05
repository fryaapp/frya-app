import { useState } from 'react'
import { CardBlock } from './CardBlock'
import { useFryaStore } from '../../stores/fryaStore'

interface CardListBlockData {
  title?: string
  initial_count?: number
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
  const [expanded, setExpanded] = useState(false)

  const INITIAL_COUNT = data.initial_count || 5
  const items = data?.items || []
  const visibleItems = expanded ? items : items.slice(0, INITIAL_COUNT)
  const hiddenCount = items.length - INITIAL_COUNT

  const handleCardClick = (item: CardListBlockData['items'][0]) => {
    const name = item.title || 'Beleg'
    const msg = `Zeig mir ${name}`
    addUserMessage(msg)
    if (item.case_id) {
      send({ text: msg, quick_action: { type: 'show_case', params: { case_id: item.case_id } } })
    } else {
      send({ text: msg })
    }
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
      {visibleItems.map((item, i) => (
        <div key={i} onClick={() => handleCardClick(item)} style={{ cursor: 'pointer' }}>
          <CardBlock data={item} />
        </div>
      ))}
      {!expanded && hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(true)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            padding: '8px 16px',
            fontSize: 12,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            fontWeight: 500,
            color: 'var(--frya-primary)',
            background: 'transparent',
            border: '1px dashed var(--frya-outline-variant)',
            borderRadius: 10,
            cursor: 'pointer',
            transition: 'background 150ms, border-color 150ms',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--frya-surface-variant)'
            e.currentTarget.style.borderColor = 'var(--frya-primary)'
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'transparent'
            e.currentTarget.style.borderColor = 'var(--frya-outline-variant)'
          }}
        >
          {'\u25BC'} Weitere {hiddenCount} anzeigen
        </button>
      )}
      {expanded && hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(false)}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            padding: '6px 16px',
            fontSize: 11,
            fontFamily: 'Plus Jakarta Sans, sans-serif',
            color: 'var(--frya-on-surface-variant)',
            background: 'transparent',
            border: 'none',
            cursor: 'pointer',
          }}
        >
          {'\u25B2'} Weniger anzeigen
        </button>
      )}
    </div>
  )
}
