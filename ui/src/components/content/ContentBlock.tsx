import { CardBlock } from './CardBlock'
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

interface ContentBlockProps {
  block: {
    block_type: string
    data: any
  }
  onAction?: (action: any) => void
  onSubmit?: (formType: string, formData: Record<string, any>) => void
}

export function ContentBlock({ block, onAction, onSubmit }: ContentBlockProps) {
  if (!block || !block.data) return null

  switch (block.block_type) {
    case 'card':
      return <CardBlock data={block.data} />
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
    default:
      return null
  }
}
