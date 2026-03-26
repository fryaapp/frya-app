import { create } from 'zustand'

export type ContextType = 'none' | 'inbox' | 'case_detail' | 'deadlines' | 'finance' | 'upload_status' | 'document_preview' | 'documents' | 'cases' | 'settings' | 'profile' | 'legal' | 'feedback'

interface UiState {
  /** Whether the split view is open (chat visible at bottom) */
  splitOpen: boolean
  /** What content the context panel (top part) shows */
  contextType: ContextType
  /** Open the split view with a specific context */
  openSplit: (ctx: ContextType) => void
  /** Close the split view, return to idle */
  closeSplit: () => void
  /** Set context type without opening/closing */
  setContextType: (ctx: ContextType) => void
}

export const useUiStore = create<UiState>((set) => ({
  splitOpen: false,
  contextType: 'none',

  openSplit: (ctx) => set({ splitOpen: true, contextType: ctx }),
  closeSplit: () => set({ splitOpen: false, contextType: 'none' }),
  setContextType: (ctx) => set({ contextType: ctx }),
}))
