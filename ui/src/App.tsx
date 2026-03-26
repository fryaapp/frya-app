import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import { useTheme } from './hooks/useTheme'
import { LoginPage } from './pages/LoginPage'
import { AppShell } from './components/layout'
import { OnboardingPage } from './pages/OnboardingPage'
import { InboxPage } from './pages/InboxPage'
import { CasesPage } from './pages/CasesPage'
import { DeadlinesPage } from './pages/DeadlinesPage'
import { UploadPage } from './pages/UploadPage'
import { SettingsPage } from './pages/SettingsPage'
import { FeedbackPage } from './pages/FeedbackPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { FinancePage } from './pages/FinancePage'
import { ProfilePage } from './pages/ProfilePage'
import { LegalPage } from './pages/LegalPage'
import './index.css'

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
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/onboarding" element={<ProtectedRoute><OnboardingPage /></ProtectedRoute>} />
        <Route element={<ProtectedRoute><AppShell /></ProtectedRoute>}>
          {/* Home shows StartPage (idle) via SplitView.idleContent */}
          <Route index element={<PlaceholderContext label="Start" />} />
          {/* Context panel pages (top 58% of split) */}
          <Route path="inbox" element={<InboxPage />} />
          <Route path="cases" element={<CasesPage />} />
          <Route path="deadlines" element={<DeadlinesPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="feedback" element={<FeedbackPage />} />
          <Route path="documents" element={<DocumentsPage />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="legal" element={<LegalPage />} />
          {/* Phase 2 routes — prepared but not built */}
          <Route path="finance" element={<FinancePage />} />
          <Route path="bookings" element={<PlaceholderContext label="Buchungsjournal" />} />
          <Route path="contacts" element={<PlaceholderContext label="Kontakte" />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

/** Temporary placeholder for Phase 2 context panels */
function PlaceholderContext({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-full p-8">
      <p className="text-on-surface-variant text-lg">{label} — Phase 2</p>
    </div>
  )
}
