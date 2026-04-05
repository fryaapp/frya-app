import { useState, useRef, useEffect, useCallback } from 'react'
import { CardBlock } from './CardBlock'
import { useFryaStore } from '../../stores/fryaStore'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CardGroupItem {
  title?: string
  subtitle?: string
  amount?: string
  badge?: { label: string; color: string }
  ai_label?: string
  case_id?: string
}

interface CardGroup {
  name: string
  reference?: string
  group_type?: string // "recurring" | "dunning_chain" | "same_contract" | "same_vendor"
  total_amount?: string
  count: number
  highest_badge?: { label: string; color: string }
  warning?: string
  items: CardGroupItem[]
}

interface CardGroupBlockData {
  groups: CardGroup[]
  ungrouped_items?: CardGroupItem[]
}

// ---------------------------------------------------------------------------
// Badge color mapping
// ---------------------------------------------------------------------------

const BADGE_COLOR_MAP: Record<string, { bg: string; fg: string }> = {
  success: { bg: 'var(--frya-success-container)', fg: 'var(--frya-success)' },
  info: { bg: 'var(--frya-info-container)', fg: 'var(--frya-info)' },
  warning: { bg: 'var(--frya-warning-container)', fg: 'var(--frya-warning)' },
  error: { bg: 'var(--frya-error-container)', fg: 'var(--frya-error)' },
}

const LABEL_TO_COLOR: Record<string, string> = {
  Sicher: 'success',
  Hoch: 'info',
  Mittel: 'warning',
  Niedrig: 'error',
}

function resolveBadgeColor(color: string): { bg: string; fg: string } {
  return BADGE_COLOR_MAP[color] || BADGE_COLOR_MAP.info
}

// ---------------------------------------------------------------------------
// Helper: check if all items qualify for "Alle freigeben"
// ---------------------------------------------------------------------------

function allItemsApprovable(items: CardGroupItem[]): boolean {
  if (items.length === 0) return false
  return items.every(
    (item) =>
      item.badge != null &&
      (item.badge.label === 'Sicher' || item.badge.label === 'Hoch'),
  )
}

// ---------------------------------------------------------------------------
// Animated expand/collapse wrapper
// ---------------------------------------------------------------------------

function AnimatedPanel({
  open,
  children,
}: {
  open: boolean
  children: React.ReactNode
}) {
  const contentRef = useRef<HTMLDivElement>(null)
  const [maxHeight, setMaxHeight] = useState<string>(open ? 'none' : '0px')
  const [overflow, setOverflow] = useState<string>(open ? 'visible' : 'hidden')

  useEffect(() => {
    const el = contentRef.current
    if (!el) return

    if (open) {
      // Measure the full scroll height and set it as max-height for the animation
      setOverflow('hidden')
      setMaxHeight(`${el.scrollHeight}px`)
      const timer = setTimeout(() => {
        setMaxHeight('none')
        setOverflow('visible')
      }, 310)
      return () => clearTimeout(timer)
    } else {
      // Collapse: first set explicit height so transition can animate from it
      setMaxHeight(`${el.scrollHeight}px`)
      setOverflow('hidden')
      // Force reflow before collapsing
      void el.offsetHeight
      requestAnimationFrame(() => {
        setMaxHeight('0px')
      })
    }
  }, [open])

  return (
    <div
      ref={contentRef}
      style={{
        maxHeight,
        overflow,
        transition: 'max-height 300ms ease-in-out',
      }}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Single group accordion
// ---------------------------------------------------------------------------

function GroupAccordion({
  group,
  onCardClick,
  onApproveAll,
}: {
  group: CardGroup
  onCardClick: (item: CardGroupItem) => void
  onApproveAll: (group: CardGroup) => void
}) {
  const [open, setOpen] = useState(false)
  const [headerHovered, setHeaderHovered] = useState(false)

  const badge = group.highest_badge
  const badgeColor = badge
    ? resolveBadgeColor(LABEL_TO_COLOR[badge.label] || badge.color)
    : null
  const showApproveAll = open && allItemsApprovable(group.items)

  return (
    <div
      style={{
        borderRadius: 12,
        border: open
          ? '1px solid #F08A3A'
          : '1px solid var(--frya-outline-variant)',
        background: 'var(--frya-surface)',
        overflow: 'hidden',
        transition: 'border-color 200ms ease',
      }}
    >
      {/* Collapsed / header */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen((prev) => !prev)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((prev) => !prev)
          }
        }}
        onMouseEnter={() => setHeaderHovered(true)}
        onMouseLeave={() => setHeaderHovered(false)}
        style={{
          cursor: 'pointer',
          padding: '10px 14px',
          background: headerHovered
            ? 'var(--frya-surface-container-high)'
            : 'var(--frya-surface-container-low)',
          transition: 'background 150ms ease',
          userSelect: 'none',
        }}
      >
        {/* First line: chevron + name + reference */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: open ? '#F08A3A' : 'var(--frya-on-surface-variant)',
              transition: 'transform 200ms ease, color 200ms ease',
              display: 'inline-block',
              transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
              flexShrink: 0,
            }}
          >
            {'\u25B6'}
          </span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: 'var(--frya-on-surface)',
              fontFamily: "'Plus Jakarta Sans', sans-serif",
              lineHeight: 1.3,
            }}
          >
            {group.name}
          </span>
          {group.reference && (
            <span
              style={{
                fontSize: 11,
                color: 'var(--frya-on-surface-variant)',
                fontFamily: "'Plus Jakarta Sans', sans-serif",
              }}
            >
              {group.reference}
            </span>
          )}
        </div>

        {/* Second line: count + total_amount + badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 4,
            paddingLeft: 19, // align with name (chevron width + gap)
          }}
        >
          <span
            style={{
              fontSize: 11,
              color: 'var(--frya-on-surface-variant)',
              fontFamily: "'Plus Jakarta Sans', sans-serif",
            }}
          >
            {group.count} {group.count === 1 ? 'Beleg' : 'Belege'}
          </span>
          {group.total_amount && (
            <span
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: 'var(--frya-on-surface)',
                fontFamily: 'Outfit, sans-serif',
                whiteSpace: 'nowrap',
              }}
            >
              {group.total_amount}
            </span>
          )}
          {badge && badgeColor && (
            <span
              style={{
                display: 'inline-block',
                padding: '1px 7px',
                borderRadius: 6,
                fontSize: 10,
                fontWeight: 600,
                fontFamily: "'Plus Jakarta Sans', sans-serif",
                background: badgeColor.bg,
                color: badgeColor.fg,
              }}
            >
              {badge.label}
            </span>
          )}
        </div>

        {/* Warning line */}
        {group.warning && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              marginTop: 4,
              paddingLeft: 19,
            }}
          >
            <span style={{ fontSize: 12 }}>{'\u26A0'}</span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 500,
                color: '#E67E22',
                fontFamily: "'Plus Jakarta Sans', sans-serif",
              }}
            >
              {group.warning}
            </span>
          </div>
        )}
      </div>

      {/* Expanded: items */}
      <AnimatedPanel open={open}>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            padding: '8px 10px',
          }}
        >
          {group.items.map((item, i) => (
            <div
              key={item.case_id || i}
              onClick={() => onCardClick(item)}
              style={{ cursor: 'pointer', borderRadius: 10 }}
            >
              <CardBlock data={item} />
            </div>
          ))}

          {/* "Alle freigeben" button */}
          {showApproveAll && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onApproveAll(group)
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 6,
                padding: '8px 16px',
                marginTop: 4,
                fontSize: 12,
                fontFamily: "'Plus Jakarta Sans', sans-serif",
                fontWeight: 600,
                color: '#FFFFFF',
                background: '#F08A3A',
                border: 'none',
                borderRadius: 10,
                cursor: 'pointer',
                transition: 'background 150ms ease, transform 100ms ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = '#D97A2F'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = '#F08A3A'
              }}
              onMouseDown={(e) => {
                e.currentTarget.style.transform = 'scale(0.97)'
              }}
              onMouseUp={(e) => {
                e.currentTarget.style.transform = 'scale(1)'
              }}
            >
              Alle freigeben
            </button>
          )}
        </div>
      </AnimatedPanel>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CardGroupBlock({ data }: { data: CardGroupBlockData }) {
  const send = useFryaStore((s) => s.send)
  const addUserMessage = useFryaStore((s) => s.addUserMessage)

  const handleCardClick = useCallback(
    (item: CardGroupItem) => {
      const name = item.title || 'Beleg'
      const msg = `Zeig mir ${name}`
      addUserMessage(msg)
      if (item.case_id) {
        send({ type: 'message', text: msg, quick_action: { type: 'show_case', params: { case_id: item.case_id } } })
      } else {
        send({ type: 'message', text: msg })
      }
    },
    [send, addUserMessage],
  )

  const handleApproveAll = useCallback(
    (group: CardGroup) => {
      const msg = `Alle freigeben: ${group.name}`
      addUserMessage(msg)
      send({ type: 'message', text: msg })
    },
    [send, addUserMessage],
  )

  const groups = data.groups || []
  const ungrouped = data.ungrouped_items || []

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        fontFamily: "'Plus Jakarta Sans', sans-serif",
      }}
    >
      {/* Grouped items */}
      {groups.map((group, i) => (
        <GroupAccordion
          key={`${group.name}-${i}`}
          group={group}
          onCardClick={handleCardClick}
          onApproveAll={handleApproveAll}
        />
      ))}

      {/* Ungrouped items */}
      {ungrouped.length > 0 &&
        ungrouped.map((item, i) => (
          <div
            key={item.case_id || `ungrouped-${i}`}
            onClick={() => handleCardClick(item)}
            style={{ cursor: 'pointer' }}
          >
            <CardBlock data={item} />
          </div>
        ))}
    </div>
  )
}
