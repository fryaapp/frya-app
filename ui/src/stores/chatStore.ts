import { create } from 'zustand'

export type MessageRole = 'user' | 'assistant' | 'system'

export interface ApprovalData {
  case_id: string
  case_number?: string
  vendor: string
  amount: number
  currency?: string
  document_type?: string
  buttons: string[]
}

export interface DuplicateData {
  original_title: string
  paperless_id: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  timestamp: number
  suggestions?: string[]
  caseRef?: string | null
  contextType?: string
  isStreaming?: boolean
  // Special message types
  approval?: ApprovalData
  duplicate?: DuplicateData
  notificationType?: string
  // Approval state (after user action)
  approvalAction?: string
}

interface ChatState {
  messages: ChatMessage[]
  isTyping: boolean
  typingHint: string | null
  addUserMessage: (text: string) => void
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

let msgCounter = 0

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isTyping: false,
  typingHint: null,

  addUserMessage: (text) => {
    const id = `user-${++msgCounter}`
    set((s) => ({
      messages: [...s.messages, { id, role: 'user', text, timestamp: Date.now() }],
    }))
  },

  startAssistantMessage: () => {
    const id = `assistant-${++msgCounter}`
    set((s) => ({
      messages: [...s.messages, { id, role: 'assistant', text: '', timestamp: Date.now(), isStreaming: true }],
    }))
    return id
  },

  appendChunk: (id, text) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, text: m.text + text } : m,
      ),
    }))
  },

  completeMessage: (id, text, suggestions, caseRef, contextType) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, text, isStreaming: false, suggestions, caseRef, contextType } : m,
      ),
    }))
  },

  addApprovalRequest: (data) => {
    const id = `approval-${++msgCounter}`
    set((s) => ({
      messages: [...s.messages, {
        id,
        role: 'system' as MessageRole,
        text: '',
        timestamp: Date.now(),
        approval: data,
      }],
    }))
  },

  addNotification: (text, notificationType) => {
    const id = `notif-${++msgCounter}`
    set((s) => ({
      messages: [...s.messages, {
        id,
        role: 'system' as MessageRole,
        text,
        timestamp: Date.now(),
        notificationType,
      }],
    }))
  },

  addDuplicate: (data) => {
    const id = `dup-${++msgCounter}`
    set((s) => ({
      messages: [...s.messages, {
        id,
        role: 'system' as MessageRole,
        text: '',
        timestamp: Date.now(),
        duplicate: data,
      }],
    }))
  },

  setApprovalAction: (messageId, action) => {
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === messageId ? { ...m, approvalAction: action } : m,
      ),
    }))
  },

  setTyping: (v, hint) => set({ isTyping: v, typingHint: hint ?? null }),
  clear: () => set({ messages: [], isTyping: false, typingHint: null }),
}))
