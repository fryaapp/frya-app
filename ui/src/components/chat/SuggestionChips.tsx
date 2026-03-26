import { Chip } from '../m3'

interface SuggestionChipsProps {
  suggestions: string[]
  onSelect: (text: string) => void
}

export function SuggestionChips({ suggestions, onSelect }: SuggestionChipsProps) {
  if (!suggestions.length) return null
  return (
    <div className="flex flex-wrap gap-2 px-4 pb-2">
      {suggestions.map((s) => (
        <Chip key={s} label={s} color="primary" onClick={() => onSelect(s)} />
      ))}
    </div>
  )
}
