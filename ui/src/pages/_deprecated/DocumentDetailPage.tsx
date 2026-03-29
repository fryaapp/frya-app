import { useEffect, useRef, useState } from 'react'
import { useParams, useLocation, useNavigate } from 'react-router-dom'
import { Button, Card, Icon } from '../components/m3'
import { api } from '../lib/api'

interface DocumentState {
  id: string
  title: string
  correspondent: string | null
  document_type: string | null
  tags: string[]
  created_at: string
  thumbnail_url: string | null
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

export function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  const doc = (location.state as { document?: DocumentState } | null)?.document ?? null

  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const blobUrlRef = useRef<string | null>(null)

  useEffect(() => {
    if (!id) return

    let cancelled = false

    api
      .getBlob(`/documents/${id}/thumbnail`)
      .then((blob) => {
        if (cancelled) return
        const url = URL.createObjectURL(blob)
        blobUrlRef.current = url
        setThumbUrl(url)
      })
      .catch(() => {
        if (!cancelled) setError('Vorschau konnte nicht geladen werden.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [id])

  useEffect(() => {
    return () => {
      if (blobUrlRef.current) URL.revokeObjectURL(blobUrlRef.current)
    }
  }, [])

  const handleDownload = () => {
    if (!thumbUrl) return
    const a = document.createElement('a')
    a.href = thumbUrl
    a.download = doc?.title ? `${doc.title}.png` : `dokument-${id}.png`
    a.click()
  }

  if (!id) return null

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <button
          onClick={() => navigate(-1)}
          className="p-1 -ml-1 rounded-full hover:bg-surface-variant transition-colors"
          aria-label="Zurück"
        >
          <Icon name="arrow_back" size={24} className="text-on-surface" />
        </button>
        <h1 className="text-lg font-display font-bold text-on-surface truncate flex-1">
          {doc?.title ?? 'Dokument'}
        </h1>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Vorschau&hellip;</p>
          </div>
        )}

        {!loading && error && !thumbUrl && (
          <div className="flex flex-col items-center justify-center py-16">
            <Icon name="broken_image" size={48} className="text-error mb-3" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {!loading && thumbUrl && (
          <div className="w-full rounded-lg overflow-hidden bg-surface-variant flex items-center justify-center">
            <img
              src={thumbUrl}
              alt={doc?.title ?? 'Dokumentvorschau'}
              className="w-full h-auto object-contain max-h-[60vh]"
            />
          </div>
        )}

        {/* Metadata */}
        {doc && (
          <Card variant="outlined">
            <div className="space-y-2">
              <div>
                <p className="text-xs text-on-surface-variant">Titel</p>
                <p className="text-sm font-semibold text-on-surface">{doc.title}</p>
              </div>
              {doc.document_type && (
                <div>
                  <p className="text-xs text-on-surface-variant">Dokumenttyp</p>
                  <p className="text-sm text-on-surface">{doc.document_type}</p>
                </div>
              )}
              <div>
                <p className="text-xs text-on-surface-variant">Datum</p>
                <p className="text-sm text-on-surface">{formatDate(doc.created_at)}</p>
              </div>
              {doc.correspondent && (
                <div>
                  <p className="text-xs text-on-surface-variant">Korrespondent</p>
                  <p className="text-sm text-on-surface">{doc.correspondent}</p>
                </div>
              )}
              {doc.tags.length > 0 && (
                <div>
                  <p className="text-xs text-on-surface-variant mb-1">Tags</p>
                  <div className="flex flex-wrap gap-1">
                    {doc.tags.map((tag) => (
                      <span
                        key={tag}
                        className="inline-block px-2 py-0.5 rounded-full bg-secondary-container text-on-secondary-container text-xs"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Card>
        )}

        {/* Actions */}
        <div className="flex gap-3">
          <Button variant="outlined" onClick={() => navigate(-1)} className="flex-1">
            Zurück
          </Button>
          <Button
            variant="filled"
            onClick={handleDownload}
            disabled={!thumbUrl}
            className="flex-1"
          >
            Herunterladen
          </Button>
        </div>
      </div>
    </div>
  )
}
