import { useCallback, useState } from 'react'
import { Card, Icon } from '../components/m3'
import { Dropzone } from '../components/upload/Dropzone'
import { PipelineStatus } from '../components/upload/PipelineStatus'
import type { FileStatus } from '../components/upload/types'
import { api } from '../lib/api'

interface BulkUploadResult {
  processed: number
  cases_created: number
  needs_review: number
  results: Array<{
    filename: string
    status: string
    case_id?: string
    error?: string
  }>
}

export function UploadPage() {
  const [files, setFiles] = useState<FileStatus[]>([])
  const [metrics, setMetrics] = useState<{ processed: number; cases: number; review: number } | null>(null)

  const handleFiles = useCallback(async (incoming: File[]) => {
    // Initialize all files as pending
    const initial: FileStatus[] = incoming.map((f) => ({
      name: f.name,
      size: f.size,
      status: 'pending' as const,
    }))
    setFiles(initial)
    setMetrics(null)

    // Transition all to uploading
    setFiles(incoming.map((f) => ({ name: f.name, size: f.size, status: 'uploading' as const })))

    try {
      // Note: bulk-upload is at /api/documents/bulk-upload (no /v1/)
      const form = new FormData()
      incoming.forEach((f) => form.append('files', f))
      const h: Record<string, string> = {}
      const token = localStorage.getItem('frya-token')
      if (token) h['Authorization'] = `Bearer ${token}`
      const res = await fetch('/api/documents/bulk-upload', { method: 'POST', headers: h, body: form })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const result = await res.json() as BulkUploadResult

      // Map backend results to file statuses
      const updated: FileStatus[] = incoming.map((f) => {
        const r = result.results.find((res) => res.filename === f.name)
        if (!r) return { name: f.name, size: f.size, status: 'done' as const }

        const statusMap: Record<string, FileStatus['status']> = {
          processed: 'done',
          duplicate: 'duplicate',
          error: 'error',
        }

        return {
          name: f.name,
          size: f.size,
          status: statusMap[r.status] ?? 'done',
          error: r.error,
        }
      })

      setFiles(updated)
      setMetrics({
        processed: result.processed,
        cases: result.cases_created,
        review: result.needs_review,
      })
    } catch {
      // Mark all as error
      setFiles(incoming.map((f) => ({
        name: f.name,
        size: f.size,
        status: 'error' as const,
        error: 'Upload fehlgeschlagen',
      })))
    }
  }, [])

  const uploading = files.some((f) => f.status === 'uploading')

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="laundry" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Wäschekorb</h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {/* Dropzone */}
        <Dropzone onFiles={handleFiles} disabled={uploading} />

        {/* File pipeline */}
        {files.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide">
              Dateien ({files.length})
            </p>
            <PipelineStatus files={files} />
          </div>
        )}

        {/* Metric cards */}
        {metrics && (
          <div className="grid grid-cols-3 gap-3">
            <Card variant="outlined">
              <div className="flex flex-col items-center gap-1">
                <Icon name="task_alt" size={28} className="text-success" />
                <p className="text-xl font-bold text-on-surface">{metrics.processed}</p>
                <p className="text-xs text-on-surface-variant">Verarbeitet</p>
              </div>
            </Card>
            <Card variant="outlined">
              <div className="flex flex-col items-center gap-1">
                <Icon name="folder_open" size={28} className="text-info" />
                <p className="text-xl font-bold text-on-surface">{metrics.cases}</p>
                <p className="text-xs text-on-surface-variant">Vorgänge</p>
              </div>
            </Card>
            <Card variant="outlined">
              <div className="flex flex-col items-center gap-1">
                <Icon name="rate_review" size={28} className="text-warning" />
                <p className="text-xl font-bold text-on-surface">{metrics.review}</p>
                <p className="text-xs text-on-surface-variant">Brauchen dich</p>
              </div>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
