import { useLocation, useNavigate } from 'react-router-dom'
import { Icon } from '../m3'
import { useUiStore, type ContextType } from '../../stores/uiStore'

interface NavItem {
  path: string
  icon: string
  context: ContextType
  disabled?: boolean
}

const navItems: NavItem[] = [
  { path: '/', icon: 'home', context: 'none' },
  { path: '/inbox', icon: 'inbox', context: 'inbox' },
  { path: '/cases', icon: 'folder_open', context: 'cases' },
  { path: '/finance', icon: 'bar_chart', context: 'finance', disabled: true },
  { path: '/deadlines', icon: 'schedule', context: 'deadlines' },
  { path: '/upload', icon: 'cloud_upload', context: 'upload_status' },
]

const settingsItem: NavItem = {
  path: '/settings',
  icon: 'settings',
  context: 'settings',
}

interface IconRailProps {
  className?: string
}

/**
 * IconRail -- Vertikale Navigation fuer Desktop (>=768px).
 * 52px breit, surface-container-low, Logo oben, Settings unten.
 */
export function IconRail({ className = '' }: IconRailProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const openSplit = useUiStore((s) => s.openSplit)
  const closeSplit = useUiStore((s) => s.closeSplit)
  const inboxCount = 0 // TODO: add inboxCount to uiStore when notification system is built

  const isActive = (path: string) =>
    location.pathname === path ||
    (path !== '/' && location.pathname.startsWith(path))

  const handleNav = (item: NavItem) => {
    if (item.disabled) return
    if (item.path === '/') {
      closeSplit()
      navigate('/')
    } else {
      openSplit(item.context)
      navigate(item.path)
    }
  }

  return (
    <nav
      className={`flex-col items-center w-[52px] min-w-[52px] bg-surface-container-low border-r border-outline-variant py-3.5 ${className}`}
    >
      {/* Logo */}
      <div className="w-8 h-8 rounded-m3 bg-primary-container flex items-center justify-center mb-4">
        <Icon name="eco" size={18} className="text-on-primary-container" />
      </div>

      {/* Nav-Items */}
      <div className="flex flex-col items-center gap-[3px]">
        {navItems.map((item) => {
          const active = isActive(item.path)
          return (
            <button
              key={item.path}
              onClick={() => handleNav(item)}
              disabled={item.disabled}
              className={`relative w-9 h-9 rounded-m3 flex items-center justify-center transition-colors
                ${item.disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-surface-container-high cursor-pointer'}
                ${active && !item.disabled ? 'bg-surface-container' : ''}
              `}
              aria-label={item.icon}
            >
              <Icon
                name={item.icon}
                size={20}
                filled={active && !item.disabled}
                className={
                  active && !item.disabled
                    ? 'text-primary'
                    : 'text-on-surface-variant'
                }
              />
              {/* Notification-Dot fuer Inbox */}
              {item.path === '/inbox' && inboxCount > 0 && (
                <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-error" />
              )}
            </button>
          )
        })}
      </div>

      {/* Spacer */}
      <div className="mt-auto" />

      {/* Settings ganz unten */}
      <button
        onClick={() => handleNav(settingsItem)}
        className={`w-9 h-9 rounded-m3 flex items-center justify-center transition-colors hover:bg-surface-container-high cursor-pointer
          ${isActive(settingsItem.path) ? 'bg-surface-container' : ''}
        `}
        aria-label="Einstellungen"
      >
        <Icon
          name="settings"
          size={20}
          filled={isActive(settingsItem.path)}
          className={
            isActive(settingsItem.path)
              ? 'text-primary'
              : 'text-on-surface-variant'
          }
        />
      </button>
    </nav>
  )
}
