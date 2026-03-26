import type { FileStatus } from './types'

const STATUS_LABELS: Record<FileStatus['status'], string> = {
  pending: 'Wartet',
  uploading: 'Hochladen',
  processing: 'Wird analysiert',
  done: 'Zugeordnet',
  error: 'Fehler',
  duplicate: 'Duplikat erkannt',
}

const DOT_COLORS: Record<FileStatus['status'], string> = {
  pending: 'bg-outline',
  uploading: 'bg-info animate-pulse',
  processing: 'bg-warning animate-pulse',
  done: 'bg-success',
  error: 'bg-error',
  duplicate: 'bg-warning',
}

const TEXT_COLORS: Record<FileStatus['status'], string> = {
  pending: 'text-on-surface-variant',
  uploading: 'text-info',
  processing: 'text-warning',
  done: 'text-success',
  error: 'text-error',
  duplicate: 'text-warning',
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface PipelineStatusProps {
  files: FileStatus[]
}

export function PipelineStatus({ files }: PipelineStatusProps) {
  if (files.length === 0) return null

  return (
    <div className="flex flex-col gap-1">
      {files.map((f, i) => (
        <div
          key={`${f.name}-${i}`}
          className="flex items-center gap-3 px-3 py-2 rounded-m3-sm bg-surface-container"
        >
          {/* Status dot */}
          <span className={`flex-shrink-0 w-2.5 h-2.5 rounded-full ${DOT_COLORS[f.status]}`} />

          {/* Filename */}
          <span className="flex-1 min-w-0 text-sm text-on-surface truncate">{f.name}</span>

          {/* Size */}
          <span className="flex-shrink-0 text-xs text-on-surface-variant">
            {formatSize(f.size)}
          </span>

          {/* Status label */}
          <span className={`flex-shrink-0 text-xs font-semibold ${TEXT_COLORS[f.status]}`}>
            {STATUS_LABELS[f.status]}
          </span>
        </div>
      ))}
    </div>
  )
}
