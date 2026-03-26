import type { DuplicateData } from '../../stores/chatStore'
import { Icon } from '../m3'

interface DuplicateCardProps {
  data: DuplicateData
}

export function DuplicateCard({ data }: DuplicateCardProps) {
  return (
    <div className="flex justify-start mb-3">
      <div className="max-w-[85%] bg-warning-container/30 border border-warning/30 rounded-m3-lg px-4 py-3 flex items-start gap-3">
        <Icon name="content_copy" size={20} className="text-warning shrink-0 mt-0.5" />
        <div>
          <p className="text-sm font-semibold text-on-surface">Duplikat erkannt</p>
          <p className="text-xs text-on-surface-variant mt-1">
            Dieses Dokument hab ich bereits: <span className="font-medium">{data.original_title}</span>
          </p>
        </div>
      </div>
    </div>
  )
}
