import React from 'react'
import { CardBlock } from './CardBlock'
import { CardGroupBlock } from './CardGroupBlock'
import { CardListBlock } from './CardListBlock'
import { TableBlock } from './TableBlock'
import { ChartBlock } from './ChartBlock'
import { FormBlock } from './FormBlock'
import { DocumentBlock } from './DocumentBlock'
import { KeyValueBlock } from './KeyValueBlock'
import { ProgressBlock } from './ProgressBlock'
import { AlertBlock } from './AlertBlock'
import { ExportBlock } from './ExportBlock'
import { StatusBlock } from './StatusBlock'
import { useFryaStore } from '../../stores/fryaStore'

interface ContentBlockProps {
  block: {
    block_type: string
    data: any
  }
  onAction?: (action: any) => void
  onSubmit?: (formType: string, formData: Record<string, any>) => void
}

/** Safety wrapper — if a single block crashes, show nothing instead of crashing the whole chat. */
class BlockErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false }
  static getDerivedStateFromError() { return { hasError: true } }
  componentDidCatch(err: Error) {
    console.warn('[ContentBlock] render error:', err.message)
  }
  render() {
    return this.state.hasError ? null : this.props.children
  }
}

export function ContentBlock({ block, onAction, onSubmit }: ContentBlockProps) {
  if (!block || !block.data) return null

  return (
    <BlockErrorBoundary>
      <ContentBlockInner block={block} onAction={onAction} onSubmit={onSubmit} />
    </BlockErrorBoundary>
  )
}

function ContentBlockInner({ block, onAction, onSubmit }: ContentBlockProps) {
  switch (block.block_type) {
    case 'card':
      return <CardBlock data={block.data} />
    case 'card_group':
      return <CardGroupBlock data={block.data} />
    case 'card_list':
      return <CardListBlock data={block.data} />
    case 'table':
      return <TableBlock data={block.data} />
    case 'chart':
      return <ChartBlock data={block.data} />
    case 'form':
      return <FormBlock data={block.data} onSubmit={onSubmit} />
    case 'document':
      return <DocumentBlock data={block.data} />
    case 'key_value':
      return <KeyValueBlock data={block.data} />
    case 'progress':
      return <ProgressBlock data={block.data} />
    case 'alert':
      return <AlertBlock data={block.data} />
    case 'export':
      return <ExportBlock data={block.data} onAction={onAction} />
    case 'status':
      return <StatusBlock data={block.data} />
    case 'action':
      return <ActionButton data={block.data} />
    default:
      return null
  }
}

function ActionButton({ data }: { data: { label: string; chat_text: string; style?: string; icon?: string } }) {
  const send = useFryaStore((s) => s.send)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)

  return (
    <button
      onClick={() => {
        const msg = data.chat_text || data.label
        addUserMessage(msg)
        send({ text: msg })
      }}
      style={{
        width: '100%',
        padding: '10px 16px',
        fontSize: 12,
        fontWeight: 600,
        fontFamily: "'Inter Variable', 'Inter', sans-serif",
        borderRadius: 10,
        border: '1px solid var(--frya-outline-variant)',
        background: 'var(--frya-surface-container-low)',
        color: 'var(--frya-primary)',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        transition: 'background 0.15s, border-color 0.15s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--frya-surface-container-high)'
        e.currentTarget.style.borderColor = 'var(--frya-primary)'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = 'var(--frya-surface-container-low)'
        e.currentTarget.style.borderColor = 'var(--frya-outline-variant)'
      }}
    >
      {data.icon && (
        <span className="material-symbols-rounded" style={{ fontSize: 16, fontVariationSettings: "'FILL' 0, 'wght' 400" }}>
          {data.icon}
        </span>
      )}
      {data.label}
    </button>
  )
}
