import { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '../m3'
import { useUiStore, type ContextType } from '../../stores/uiStore'

const tabs: { path: string; icon: string; label: string; context: ContextType }[] = [
  { path: '/', icon: 'home', label: 'Start', context: 'none' },
  { path: '/inbox', icon: 'inbox', label: 'Inbox', context: 'inbox' },
  { path: '/cases', icon: 'folder_open', label: 'Vorgänge', context: 'cases' },
  { path: '/deadlines', icon: 'event', label: 'Fristen', context: 'deadlines' },
]

const moreItems: { path: string; icon: string; label: string; context: ContextType }[] = [
  { path: '/documents', icon: 'description', label: 'Dokumente', context: 'documents' },
  { path: '/finance', icon: 'account_balance', label: 'Finanzen', context: 'finance' },
  { path: '/settings', icon: 'settings', label: 'Einstellungen', context: 'settings' },
  { path: '/profile', icon: 'person', label: 'Profil', context: 'profile' },
]

export function BottomNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const openSplit = useUiStore((s) => s.openSplit)
  const closeSplit = useUiStore((s) => s.closeSplit)
  const [showMore, setShowMore] = useState(false)
  const moreRef = useRef<HTMLDivElement>(null)

  // Close menu on click outside
  useEffect(() => {
    if (!showMore) return
    const handleClickOutside = (e: MouseEvent) => {
      if (moreRef.current && !moreRef.current.contains(e.target as Node)) {
        setShowMore(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showMore])

  const handleTab = (tab: typeof tabs[number]) => {
    if (tab.path === '/') {
      closeSplit()
      navigate('/')
    } else {
      openSplit(tab.context)
      navigate(tab.path)
    }
  }

  const handleMoreItem = (item: typeof moreItems[number]) => {
    setShowMore(false)
    openSplit(item.context)
    navigate(item.path)
  }

  const isMoreActive = moreItems.some((item) => location.pathname.startsWith(item.path))

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-surface-container border-t border-outline-variant/50 z-50 safe-area-bottom">
      <div className="flex justify-around items-center h-16 max-w-lg mx-auto">
        {tabs.map((tab) => {
          const active = location.pathname === tab.path ||
            (tab.path !== '/' && location.pathname.startsWith(tab.path))
          return (
            <button
              key={tab.path}
              onClick={() => handleTab(tab)}
              className="flex flex-col items-center justify-center gap-0.5 min-w-[64px] min-h-[48px] transition-colors"
            >
              <div className={`px-4 py-1 rounded-m3-lg transition-colors ${active ? 'bg-secondary-container' : ''}`}>
                <Icon name={tab.icon} size={24} filled={active} className={active ? 'text-on-secondary-container' : 'text-on-surface-variant'} />
              </div>
              <span className={`text-xs ${active ? 'font-semibold text-on-surface' : 'text-on-surface-variant'}`}>
                {tab.label}
              </span>
            </button>
          )
        })}

        {/* Mehr tab with dropdown */}
        <div ref={moreRef} className="relative">
          <button
            onClick={() => setShowMore((v) => !v)}
            className="flex flex-col items-center justify-center gap-0.5 min-w-[64px] min-h-[48px] transition-colors"
          >
            <div className={`px-4 py-1 rounded-m3-lg transition-colors ${isMoreActive || showMore ? 'bg-secondary-container' : ''}`}>
              <Icon name="more_horiz" size={24} filled={isMoreActive} className={isMoreActive || showMore ? 'text-on-secondary-container' : 'text-on-surface-variant'} />
            </div>
            <span className={`text-xs ${isMoreActive ? 'font-semibold text-on-surface' : 'text-on-surface-variant'}`}>
              Mehr
            </span>
          </button>

          {/* Dropdown menu */}
          {showMore && (
            <div className="absolute bottom-full right-0 mb-2 w-52 bg-surface-container-high rounded-m3-lg shadow-elevation-2 border border-outline-variant/30 overflow-hidden z-50">
              {moreItems.map((item) => {
                const active = location.pathname.startsWith(item.path)
                return (
                  <button
                    key={item.path}
                    onClick={() => handleMoreItem(item)}
                    className={`flex items-center gap-3 w-full px-4 py-3 text-left transition-colors hover:bg-surface-container-highest ${active ? 'bg-secondary-container/50' : ''}`}
                  >
                    <Icon name={item.icon} size={20} filled={active} className={active ? 'text-primary' : 'text-on-surface-variant'} />
                    <span className={`text-sm ${active ? 'font-semibold text-on-surface' : 'text-on-surface-variant'}`}>
                      {item.label}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
