import { useCallback, useRef, useState } from 'react'
import { Icon } from '../m3'

interface DropzoneProps {
  onFiles: (files: File[]) => void
  disabled?: boolean
  maxFiles?: number
  maxSizeMB?: number
}

const ACCEPT = 'image/*,.pdf'

export function Dropzone({ onFiles, disabled = false, maxFiles = 50, maxSizeMB = 20 }: DropzoneProps) {
  const [dragOver, setDragOver] = useState(false)
  const [warning, setWarning] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const validate = useCallback(
    (files: File[]): File[] | null => {
      setWarning(null)

      if (files.length > maxFiles) {
        setWarning(`Maximal ${maxFiles} Dateien erlaubt (${files.length} ausgewählt).`)
        return null
      }

      const tooLarge = files.filter((f) => f.size > maxSizeMB * 1024 * 1024)
      if (tooLarge.length > 0) {
        const names = tooLarge.map((f) => f.name).join(', ')
        setWarning(`Dateien zu groß (max. ${maxSizeMB} MB): ${names}`)
        return null
      }

      return files
    },
    [maxFiles, maxSizeMB],
  )

  const handleFiles = useCallback(
    (raw: FileList | null) => {
      if (!raw || raw.length === 0) return
      const files = Array.from(raw)
      const valid = validate(files)
      if (valid) onFiles(valid)
    },
    [onFiles, validate],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      if (disabled) return
      handleFiles(e.dataTransfer.files)
    },
    [disabled, handleFiles],
  )

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      if (!disabled) setDragOver(true)
    },
    [disabled],
  )

  const handleDragLeave = useCallback(() => {
    setDragOver(false)
  }, [])

  const handleClick = useCallback(() => {
    if (!disabled) inputRef.current?.click()
  }, [disabled])

  return (
    <div className="flex flex-col gap-2">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
        role="button"
        tabIndex={0}
        className={`
          flex flex-col items-center justify-center gap-3 px-6 py-10 rounded-m3-lg
          border-2 border-dashed cursor-pointer transition-all
          ${disabled ? 'opacity-40 pointer-events-none' : ''}
          ${dragOver
            ? 'border-primary bg-primary/8 scale-[1.01]'
            : 'border-outline-variant bg-surface-container-low hover:border-outline hover:bg-surface-container'
          }
        `}
      >
        <Icon
          name="upload_file"
          size={48}
          className={dragOver ? 'text-primary' : 'text-on-surface-variant'}
        />
        <p className="text-sm font-semibold text-on-surface text-center">
          Gib mir hier all deine Belege
        </p>
        <p className="text-xs text-on-surface-variant text-center">
          Bilder oder PDF &middot; max. {maxFiles} Dateien &middot; je max. {maxSizeMB}&nbsp;MB
        </p>
      </div>

      {warning && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-m3-sm bg-error-container">
          <Icon name="warning" size={18} className="text-error" />
          <p className="text-xs text-error">{warning}</p>
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
    </div>
  )
}
