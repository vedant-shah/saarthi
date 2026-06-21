import { useCallback, useEffect, useRef } from 'react'

import { ENDPOINTS } from '../lib/api'
import { useChatStore } from '../store/chatStore'

// Parse an SSE buffer into discrete events. Returns { events, remaining }.
// `remaining` is the trailing incomplete event (no double-newline yet) that
// should be carried over to the next chunk read.
// Per SSE spec (and sse_starlette), event separator is CRLF CRLF, lines are
// CRLF. Browsers' raw fetch + getReader does not normalize line endings.
function parseSSE(buffer) {
  const events = []
  const parts = buffer.split(/\r\n\r\n|\n\n/)
  const remaining = parts.pop() ?? ''
  for (const part of parts) {
    if (!part.trim()) continue
    let eventName = 'message'
    let data = ''
    for (const line of part.split(/\r\n|\n/)) {
      if (line.startsWith('event:')) eventName = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trimStart()
    }
    events.push({ event: eventName, data })
  }
  return { events, remaining }
}

function dispatchEvent(ev, fallbackSessionId) {
  const store = useChatStore.getState()
  let payload
  try {
    payload = JSON.parse(ev.data)
  } catch {
    return false
  }
  if (ev.event === 'token') {
    store.appendToken(payload.text ?? '')
  } else if (ev.event === 'done') {
    store.endTurn(payload.session_id, payload.turn_id)
    return true
  } else if (ev.event === 'error') {
    store.setError(payload.message ?? 'unknown error')
    store.endTurn(fallbackSessionId)
    return true
  }
  return false
}

export function useChat() {
  const activeMember = useChatStore((s) => s.activeMember)
  // Holds the in-flight chat request so `stop` can abort it mid-stream.
  const abortRef = useRef(null)

  // Hydrate chat from backend whenever the active member changes (mount or
  // switch). The setTimeout(0) defers the fetch by one tick so that React's
  // Strict Mode mount/unmount/remount cycle in dev can cancel the scheduled
  // fetch before it ever fires (otherwise every mount produces a "(cancelled)"
  // history request in the network tab). AbortController still handles the
  // legitimate case of switching members mid-flight.
  useEffect(() => {
    if (!activeMember) return
    let cancelled = false
    let controller = null
    const timer = setTimeout(() => {
      if (cancelled) return
      controller = new AbortController()
      fetch(ENDPOINTS.history, {
        headers: { 'X-Member-Id': activeMember },
        signal: controller.signal,
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((data) => {
          if (!data || cancelled) return
          useChatStore.getState().hydrateFromHistory(data.session_id, data.messages)
        })
        .catch((err) => {
          if (err?.name !== 'AbortError') {
            console.warn('history hydration failed:', err)
          }
        })
    }, 0)
    return () => {
      cancelled = true
      clearTimeout(timer)
      if (controller) controller.abort()
    }
  }, [activeMember])

  const send = useCallback(async (text) => {
    const store = useChatStore.getState()
    const { activeMember, setError, startTurn, endTurn, clearReplyTo } = store
    // Capture the swipe-to-reply target before we clear it; send it so the model
    // knows which message this turn is replying to.
    const reply = store.replyTo

    // If streaming got stuck (e.g. after HMR), reset before starting a new turn.
    if (store.streaming) {
      endTurn(store.sessionId)
    }

    if (!activeMember) {
      setError('No active member selected.')
      return
    }
    if (!text.trim()) return

    startTurn(text, reply)
    clearReplyTo()

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch(ENDPOINTS.chat, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Member-Id': activeMember,
        },
        body: JSON.stringify({
          message: text,
          quoted_text: reply?.text ?? null,
          quoted_role: reply?.role ?? null,
        }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        setError(res.ok ? 'no response body' : `HTTP ${res.status}`)
        endTurn(useChatStore.getState().sessionId)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let ended = false

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const { events, remaining } = parseSSE(buffer)
        buffer = remaining
        for (const ev of events) {
          if (dispatchEvent(ev, useChatStore.getState().sessionId)) ended = true
          if (ended) break
        }
        if (ended) break
      }

      // Flush trailing partial event if any (stream may end without final \n\n).
      if (!ended && buffer.trim()) {
        const { events } = parseSSE(buffer + '\n\n')
        for (const ev of events) {
          if (dispatchEvent(ev, useChatStore.getState().sessionId)) ended = true
          if (ended) break
        }
      }

      // Safety: if 'done' never arrived, unfreeze the UI.
      if (useChatStore.getState().streaming) {
        endTurn(useChatStore.getState().sessionId)
      }
    } catch (err) {
      // A user-triggered stop aborts the fetch; `stop` already reset the UI, so
      // swallow it rather than flashing an error.
      if (err?.name === 'AbortError') return
      setError(err?.message ?? String(err))
      endTurn(useChatStore.getState().sessionId)
    } finally {
      abortRef.current = null
    }
  }, [])

  // Stop the in-flight turn: abort the request, then pull the sent message back
  // into the input for editing (the store drops the placeholder + user message
  // and returns its text + reply target).
  const stop = useCallback(() => {
    abortRef.current?.abort()
    return useChatStore.getState().stopTurn()
  }, [])

  // Manual session close. NOT wired to `beforeunload`, that event fires on
  // refresh too, which would wipe the session right before /api/history can
  // hydrate it. Backend's 30-min idle timeout handles abandoned sessions.
  const closeSession = useCallback(() => {
    const { activeMember } = useChatStore.getState()
    if (!activeMember) return
    if (typeof navigator === 'undefined' || !navigator.sendBeacon) return
    const blob = new Blob(
      [JSON.stringify({ member: activeMember })],
      { type: 'application/json' }
    )
    navigator.sendBeacon(ENDPOINTS.sessionClose, blob)
  }, [])

  return { send, stop, closeSession }
}
