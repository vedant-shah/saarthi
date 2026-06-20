import { create } from 'zustand'

const STORAGE_KEY = 'activeMember'

const newMessageId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`

const readStoredMember = () => {
  try {
    return localStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

const writeStoredMember = (id) => {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* ignore, localStorage unavailable (private mode, SSR, etc.) */
  }
}

export const useChatStore = create((set, get) => ({
  messages: [],
  streaming: false,
  activeMember: readStoredMember(),
  sessionId: null,
  members: [],
  error: null,
  // Swipe-to-reply target: { role, text } of the message being replied to, or null.
  replyTo: null,

  setMembers: (list) => set({ members: list }),

  setReplyTo: (role, text) => set({ replyTo: { role, text } }),
  clearReplyTo: () => set({ replyTo: null }),

  setActiveMember: (id) => {
    writeStoredMember(id)
    set({ activeMember: id })
  },

  setSessionId: (id) => set({ sessionId: id }),

  setError: (msg) => set({ error: msg }),

  startTurn: (userText, replyTo = null) => {
    const ts = Date.now()
    const userMsg = { id: newMessageId(), role: 'user', content: userText, ts, replyTo }
    const assistantMsg = { id: newMessageId(), role: 'assistant', content: '', ts }
    set((s) => ({
      messages: [...s.messages, userMsg, assistantMsg],
      streaming: true,
      error: null,
    }))
  },

  // Immutable append to the trailing assistant placeholder. If the last
  // message isn't an assistant message, drop the token silently rather than
  // corrupt the user message.
  appendToken: (text) => {
    set((s) => {
      if (s.messages.length === 0) return s
      const lastIdx = s.messages.length - 1
      const last = s.messages[lastIdx]
      if (last.role !== 'assistant') return s
      const updated = { ...last, content: last.content + text }
      return { messages: [...s.messages.slice(0, lastIdx), updated] }
    })
  },

  endTurn: (sessionId) => {
    set({ streaming: false, sessionId: sessionId ?? get().sessionId })
  },

  resetForMemberSwitch: () => {
    set({ messages: [], sessionId: null, error: null, streaming: false })
  },

  // Replace the entire message list from a backend `/history` response.
  // Synthesizes fresh client-side ids since the server has no need to mint
  // them. Skipped when the user is mid-stream, overwriting under a live
  // stream would orphan the in-flight assistant placeholder.
  hydrateFromHistory: (sessionId, messages) => {
    if (get().streaming) return
    const ts = Date.now()
    const hydrated = messages.map((m) => ({
      id: newMessageId(),
      role: m.role,
      content: m.content,
      ts,
    }))
    set({ messages: hydrated, sessionId: sessionId ?? null, error: null })
  },
}))
