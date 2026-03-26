import { useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '../m3'
import { useUiStore, type ContextType } from '../../stores/uiStore'

const tabs: { path: string; icon: string; label: string; context: ContextType }[] = [
  { path: '/', icon: 'home', label: 'Start', context: 'none' },
  { path: '/inbox', icon: 'inbox', label: 'Inbox', context: 'inbox' },
  { path: '/cases', icon: 'folder_open', label: 'Vorgänge', context: 'cases' },
  { path: '/finance', icon: 'bar_chart', label: 'Finanzen', context: 'finance' },
]

export function BottomNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const openSplit = useUiStore((s) => s.openSplit)
  const closeSplit = useUiStore((s) => s.closeSplit)

  const handleTab = (tab: typeof tabs[number]) => {
    if (tab.path === '/') {
      closeSplit()
      navigate('/')
    } else {
      openSplit(tab.context)
      navigate(tab.path)
    }
  }

  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-surface-container-low border-t border-outline-variant z-50 safe-area-bottom md:hidden">
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
              <div
                className={`flex items-center justify-center w-[48px] h-[24px] rounded-[12px] transition-colors ${active ? 'bg-primary-container' : ''}`}
              >
                <Icon
                  name={tab.icon}
                  size={24}
                  filled={active}
                  className={active ? 'text-on-primary-container' : 'text-on-surface-variant'}
                />
              </div>
              <span
                className={`text-[10px] leading-tight ${active ? 'font-semibold text-on-primary-container' : 'text-on-surface-variant'}`}
              >
                {tab.label}
              </span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
