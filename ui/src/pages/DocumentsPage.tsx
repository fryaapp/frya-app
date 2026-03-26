import { useCallback, useEffect, useRef, useState } from 'react'
import { Card, Icon, Input } from '../components/m3'
import { api } from '../lib/api'

interface DocumentItem {
  id: string
  title: string
  correspondent: string | null
  document_type: string | null
  tags: string[]
  created_at: string
  thumbnail_url: string | null
}

interface DocumentsResponse {
  count: number
  items: DocumentItem[]
}

const PAGE_SIZE = 25

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

function ThumbnailImage({ documentId }: { documentId: string }) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const imgRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!imgRef.current) return

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          observer.disconnect()
          api
            .getBlob(`/documents/${documentId}/thumbnail`)
            .then((blob) => setSrc(URL.createObjectURL(blob)))
            .catch(() => setFailed(true))
        }
      },
      { rootMargin: '200px' },
    )

    observer.observe(imgRef.current)
    return () => observer.disconnect()
  }, [documentId])

  useEffect(() => {
    return () => {
      if (src) URL.revokeObjectURL(src)
    }
  }, [src])

  return (
    <div
      ref={imgRef}
      className="w-full aspect-[3/4] rounded-lg bg-surface-variant flex items-center justify-center overflow-hidden"
    >
      {src && !failed && (
        <img
          src={src}
          alt="Vorschau"
          className="w-full h-full object-cover"
        />
      )}
      {!src && !failed && (
        <Icon name="description" size={32} className="text-on-surface-variant opacity-40" />
      )}
      {failed && (
        <Icon name="broken_image" size={32} className="text-on-surface-variant opacity-40" />
      )}
    </div>
  )
}

export function DocumentsPage() {
  const [items, setItems] = useState<DocumentItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchDocuments = useCallback(async (search: string, offset: number, append: boolean) => {
    const isInitial = !append
    if (isInitial) setLoading(true)
    else setLoadingMore(true)

    try {
      const q = encodeURIComponent(search)
      const data = await api.get<DocumentsResponse>(
        `/documents?query=${q}&limit=${PAGE_SIZE}&offset=${offset}`,
      )
      if (append) {
        setItems((prev) => [...prev, ...data.items])
      } else {
        setItems(data.items)
      }
      setTotalCount(data.count)
      setError(null)
    } catch {
      setError('Dokumente konnten nicht geladen werden.')
    } finally {
      if (isInitial) setLoading(false)
      else setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    fetchDocuments('', 0, false)
  }, [fetchDocuments])

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    setQuery(value)

    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      fetchDocuments(value, 0, false)
    }, 300)
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const handleLoadMore = () => {
    fetchDocuments(query, items.length, true)
  }

  const hasMore = items.length < totalCount

  return (
    <div className="flex flex-col h-full">
      {/* TopBar */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-outline-variant">
        <Icon name="folder_open" size={24} className="text-primary" />
        <h1 className="text-lg font-display font-bold text-on-surface">Dokumente</h1>
        {totalCount > 0 && (
          <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-primary text-on-primary text-xs font-bold">
            {totalCount}
          </span>
        )}
      </div>

      {/* Search */}
      <div className="px-4 py-3">
        <Input
          label="Dokumente durchsuchen"
          value={query}
          onChange={handleSearchChange}
          type="search"
        />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4 py-2">
        {loading && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="hourglass_empty" size={40} className="mb-3 animate-pulse" />
            <p className="text-sm">Lade Dokumente&hellip;</p>
          </div>
        )}

        {!loading && error && (
          <div className="flex flex-col items-center justify-center py-16">
            <Icon name="error" size={40} className="text-error mb-3" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant">
            <Icon name="description" size={48} className="mb-3 opacity-50" />
            <p className="text-sm font-medium">Noch keine Dokumente im Archiv.</p>
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              {items.map((item) => (
                <Card key={item.id} variant="outlined" className="p-0 overflow-hidden">
                  <ThumbnailImage documentId={item.id} />
                  <div className="px-3 py-2">
                    <p className="text-sm font-semibold text-on-surface truncate">
                      {item.title}
                    </p>
                    {item.document_type && (
                      <p className="text-xs text-on-surface-variant truncate">
                        {item.document_type}
                      </p>
                    )}
                    <p className="text-xs text-on-surface-variant mt-0.5">
                      {formatDate(item.created_at)}
                    </p>
                  </div>
                </Card>
              ))}
            </div>

            {hasMore && (
              <div className="flex justify-center py-4">
                {loadingMore ? (
                  <div className="flex items-center gap-2 text-on-surface-variant">
                    <Icon name="hourglass_empty" size={20} className="animate-pulse" />
                    <p className="text-sm">Lade weitere&hellip;</p>
                  </div>
                ) : (
                  <button
                    onClick={handleLoadMore}
                    className="px-4 py-2 text-sm font-medium text-primary hover:bg-primary/8 rounded-full transition-colors"
                  >
                    Weitere laden
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
