import { useEffect } from 'react'
import { BrowserRouter } from 'react-router-dom'
import { Capacitor } from '@capacitor/core'
import { App as CapApp } from '@capacitor/app'
import { useFryaStore } from './stores/fryaStore'
import { useAuthStore } from './stores/authStore'
import { useTheme } from './hooks/useTheme'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { GreetingScreen } from './components/GreetingScreen'
import { ChatView } from './components/chat/ChatView'
import { SettingsScreen } from './components/SettingsScreen'
import { PdfViewer } from './components/PdfViewer'
import { BugReportFAB } from './components/layout/BugReportOverlay'
import { ErrorBoundary } from './components/shared/ErrorBoundary'
import { initPush } from './plugins/push'
import './index.css'


/**
 * App -- single-screen architecture (no route-based navigation).
 *
 * Auth sub-routes (/forgot-password, /reset-password) are handled via a
 * simple pathname check. Everything else is driven by fryaStore state:
 *   not restored  -> blank (loading)
 *   not auth      -> LoginPage
 *   showGreeting  -> GreetingScreen (placeholder until component exists)
 *   default       -> ChatView (placeholder until component exists)
 *
 * BrowserRouter is kept as a context provider so that existing pages
 * (LoginPage, ResetPasswordPage) which still import useNavigate /
 * useSearchParams do not crash. No <Routes> are used.
 */
function AppContent() {
  const isAuthenticated = useFryaStore(s => s.isAuthenticated)
  const isRestored = useFryaStore(s => s.isRestored)
  const showGreeting = useFryaStore(s => s.showGreeting)
  const showSettings = useFryaStore(s => s.showSettings)
  const pdfViewer = useFryaStore(s => s.pdfViewer)
  const closePdfViewer = useFryaStore(s => s.closePdfViewer)
  const restore = useFryaStore(s => s.restore)
  useTheme()

  useEffect(() => { restore() }, [restore])

  // Sync bridge: LoginPage still uses the old authStore. When the old store
  // gets a token (after login), re-run fryaStore.restore() so it picks up
  // the tokens from localStorage and transitions to authenticated state.
  const oldToken = useAuthStore(s => s.token)
  useEffect(() => {
    if (oldToken && !isAuthenticated) {
      restore()
    }
  }, [oldToken, isAuthenticated, restore])

  // Push-Notifications initialisieren sobald eingeloggt
  useEffect(() => {
    if (isAuthenticated) {
      initPush()
    }
  }, [isAuthenticated])

  // Android Zurück-Taste: kontextabhängig statt immer exitApp()
  // Priorität: PDF-Viewer → Settings → Chat→Home → exitApp
  useEffect(() => {
    if (!Capacitor.isNativePlatform()) return
    let handle: { remove: () => void } | null = null
    CapApp.addListener('backButton', () => {
      const s = useFryaStore.getState()
      if (s.pdfViewer) {
        s.closePdfViewer()
      } else if (s.showSettings) {
        s.goHome()
      } else if (!s.showGreeting) {
        s.goHome()
      } else {
        CapApp.exitApp()
      }
    }).then(h => { handle = h })
    return () => { handle?.remove() }
  }, [])

  if (!isRestored) return null

  // Auth sub-routes (pathname-based, no <Routes>)
  const path = window.location.pathname
  if (path === '/forgot-password') return <><ForgotPasswordPage /><BugReportFAB /></>
  if (path === '/reset-password') return <><ResetPasswordPage /><BugReportFAB /></>
  if (path === '/invite') return <><ResetPasswordPage /><BugReportFAB /></>

  if (!isAuthenticated) return <><LoginPage /><BugReportFAB /></>

  if (showSettings) {
    return (
      <>
        <SettingsScreen />
        <BugReportFAB />
      </>
    )
  }

  if (showGreeting) {
    return (
      <>
        <GreetingScreen />
        {pdfViewer && (
          <PdfViewer caseId={pdfViewer.caseId} title={pdfViewer.title} onClose={closePdfViewer} />
        )}
      </>
    )
  }

  return (
    <>
      <ChatView />
      {pdfViewer && (
        <PdfViewer caseId={pdfViewer.caseId} title={pdfViewer.title} onClose={closePdfViewer} />
      )}
    </>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      {/* BrowserRouter provides context for LoginPage (useNavigate) and
          ResetPasswordPage (useSearchParams). No <Routes> are used. */}
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ErrorBoundary>
  )
}
