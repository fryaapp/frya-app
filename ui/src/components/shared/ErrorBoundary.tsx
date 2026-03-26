import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode; fallback?: ReactNode }
interface State { hasError: boolean; error: Error | null }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || (
        <div className="flex flex-col items-center justify-center h-full p-8 text-center">
          <span className="material-symbols-rounded text-error mb-3" style={{ fontSize: 48 }}>error</span>
          <h2 className="text-lg font-display font-bold text-on-surface mb-2">Etwas ist schiefgelaufen</h2>
          <p className="text-sm text-on-surface-variant mb-4">Bitte lade die Seite neu.</p>
          <button
            onClick={() => window.location.reload()}
            className="px-6 py-2.5 bg-primary text-on-primary rounded-m3-xl font-semibold text-sm"
          >
            Neu laden
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
