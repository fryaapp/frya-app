import { useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import { useTheme } from './hooks/useTheme'
import { LoginPage } from './pages/LoginPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { AppShell } from './components/layout'
import { ErrorBoundary } from './components/shared/ErrorBoundary'
import { Icon } from './components/m3'
import './index.css'

// Code-split all pages (lazy loading)
const OnboardingPage = lazy(() => import('./pages/OnboardingPage').then(m => ({ default: m.OnboardingPage })))
const InboxPage = lazy(() => import('./pages/InboxPage').then(m => ({ default: m.InboxPage })))
const CasesPage = lazy(() => import('./pages/CasesPage').then(m => ({ default: m.CasesPage })))
const DeadlinesPage = lazy(() => import('./pages/DeadlinesPage').then(m => ({ default: m.DeadlinesPage })))
const UploadPage = lazy(() => import('./pages/UploadPage').then(m => ({ default: m.UploadPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then(m => ({ default: m.SettingsPage })))
const FeedbackPage = lazy(() => import('./pages/FeedbackPage').then(m => ({ default: m.FeedbackPage })))
const DocumentsPage = lazy(() => import('./pages/DocumentsPage').then(m => ({ default: m.DocumentsPage })))
const DocumentDetailPage = lazy(() => import('./pages/DocumentDetailPage').then(m => ({ default: m.DocumentDetailPage })))
const FinancePage = lazy(() => import('./pages/FinancePage').then(m => ({ default: m.FinancePage })))
const ProfilePage = lazy(() => import('./pages/ProfilePage').then(m => ({ default: m.ProfilePage })))
const LegalPage = lazy(() => import('./pages/LegalPage').then(m => ({ default: m.LegalPage })))
const NotificationsPage = lazy(() => import('./pages/NotificationsPage').then(m => ({ default: m.NotificationsPage })))
const CaseDetailPage = lazy(() => import('./pages/CaseDetailPage').then(m => ({ default: m.CaseDetailPage })))
const BelegDetailPage = lazy(() => import('./pages/BelegDetailPage').then(m => ({ default: m.BelegDetailPage })))

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-full">
      <Icon name="hourglass_empty" size={32} className="text-on-surface-variant animate-pulse" />
    </div>
  )
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const restore = useAuthStore((s) => s.restore)
  useTheme()

  useEffect(() => { restore() }, [restore])

  return (
    <ErrorBoundary>
    <BrowserRouter>
      <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/onboarding" element={<ProtectedRoute><OnboardingPage /></ProtectedRoute>} />
        <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
          <Route index element={<PlaceholderContext label="Start" />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="inbox/:caseId" element={<BelegDetailPage />} />
          <Route path="cases" element={<CasesPage />} />
          <Route path="cases/:caseId" element={<CaseDetailPage />} />
          <Route path="deadlines" element={<DeadlinesPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="feedback" element={<FeedbackPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="documents/:id" element={<DocumentDetailPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="legal" element={<LegalPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="finance" element={<FinancePage />} />
          <Route path="bookings" element={<PlaceholderContext label="Buchungsjournal" />} />
          <Route path="contacts" element={<PlaceholderContext label="Kontakte" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
      </Suspense>
    </BrowserRouter>
    </ErrorBoundary>
  )
}

function PlaceholderContext({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full p-8">
      <p className="text-on-surface-variant text-lg">{label} — noch nicht verfügbar</p>
    </div>
  )
}
