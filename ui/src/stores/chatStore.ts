/**
 * chatStore.ts — DEPRECATED compatibility shim.
 *
 * All chat state now lives in fryaStore.ts. This file re-exports
 * the shared types and provides a thin useChatStore Zustand store
 * so that old (unused) components (ChatPanel, StartPage, ChatBubble)
 * still compile.
 *
 * TODO: Remove this file once the old components are deleted.
 */

export type { ChatMessage, ApprovalData, DuplicateData, MessageRole } from './fryaStore'

import { create } from 'zustand'
import { useFryaStore } from './fryaStore'
import type { ChatMessage, ApprovalData, DuplicateData } from './fryaStore'

interface ChatState {
  messages: ChatMessage[]
  isTyping: boolean
  typingHint: string | null
  pendingSend: string | null
  addUserMessage: (text: string) => void
  setPendingSend: (text: string | null) => void
  startAssistantMessage: () => string
  appendChunk: (id: string, text: string) => void
  completeMessage: (id: string, text: string, suggestions?: string[], caseRef?: string | null, contextType?: string) => void
  addApprovalRequest: (data: ApprovalData) => void
  addNotification: (text: string, notificationType: string) => void
  addDuplicate: (data: DuplicateData) => void
  setApprovalAction: (messageId: string, action: string) => void
  setTyping: (v: boolean, hint?: string) => void
  clear: () => void
}

/**
 * Thin compatibility store — delegates to useFryaStore for state that
 * overlaps, stubs everything else. This is dead code (ChatPanel is no
 * longer rendered), kept only to avoid compile errors.
 */
export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isTyping: false,
  typingHint: null,
  pendingSend: null,

  setPendingSend: (text) => set({ pendingSend: text }),

  addUserMessage: (text) => {
    // Delegate to fryaStore
    useFryaStore.getState().addUserMessage(text)
  },

  startAssistantMessage: () => {
    return `compat-${Date.now()}`
  },

  appendChunk: () => {},
  completeMessage: () => {},

  addApprovalRequest: (data) => {
    useFryaStore.getState().addApprovalRequest(data)
  },

  addNotification: (text, notificationType) => {
    useFryaStore.getState().addNotification(text, notificationType)
  },

  addDuplicate: (data) => {
    useFryaStore.getState().addDuplicate(data)
  },

  setApprovalAction: (messageId, action) => {
    useFryaStore.getState().setApprovalAction(messageId, action)
  },

  setTyping: (v, hint) => set({ isTyping: v, typingHint: hint ?? null }),

  clear: () => set({ messages: [], isTyping: false, typingHint: null, pendingSend: null }),
}))
