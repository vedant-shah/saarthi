import { useRef, useEffect, useState } from 'react'
import { motion } from 'motion/react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChatStore } from '../store/chatStore'
import { useChat } from '../hooks/useChat'

function SendArrow() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M8 13V3M8 3L3.5 7.5M8 3L12.5 7.5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function TypingDots() {
  return (
    <span className="inline-flex items-end gap-1 py-1.5">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </span>
  )
}

function bubbleRadius(role, isFirstInGroup, isLastInGroup) {
  const base = 'rounded-[22px]'
  if (role === 'user') {
    return `${base} ${isLastInGroup ? 'rounded-br-md' : ''}`.trim()
  }
  return `${base} ${isLastInGroup ? 'rounded-bl-md' : ''}`.trim()
}

const TAGLINES = [
  "Let's talk money.",
  "What's on your mind today?",
  'Your money, sorted.',
  'Ask me anything finance.',
  "Let's make a plan.",
]

function greetingWord(hour) {
  if (hour < 12) return 'Good Morning'
  if (hour < 17) return 'Good Afternoon'
  return 'Good Evening'
}

// The advisor marks a new text bubble with a blank line. Split a reply into its
// bubbles; a reply with no blank line is a single bubble. Empty -> [] so the
// typing placeholder handles it.
function splitBubbles(text) {
  return text
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
}

export function Chat() {
  const messages = useChatStore((s) => s.messages)
  const streaming = useChatStore((s) => s.streaming)
  const error = useChatStore((s) => s.error)
  const setError = useChatStore((s) => s.setError)
  const activeMember = useChatStore((s) => s.activeMember)
  const replyTo = useChatStore((s) => s.replyTo)
  const setReplyTo = useChatStore((s) => s.setReplyTo)
  const clearReplyTo = useChatStore((s) => s.clearReplyTo)
  const { send } = useChat()
  const [text, setText] = useState('')
  // Picked once per mount so it stays put while typing, not on every keystroke.
  const [tagline] = useState(
    () => TAGLINES[Math.floor(Math.random() * TAGLINES.length)],
  )
  const greeting = greetingWord(new Date().getHours())
  const containerRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    const el = containerRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`
  }, [text])

  function handleSubmit() {
    const trimmed = text.trim()
    if (!trimmed || streaming) return
    setText('')
    send(trimmed)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const canSend = text.trim().length > 0 && !streaming

  return (
    <div className="flex flex-col h-full">
      <div
        ref={containerRef}
        className="flex flex-1 flex-col overflow-y-auto px-4 py-6"
      >
        {messages.length === 0 && (
          <div className="flex flex-1 flex-col items-center justify-center text-center animate-fade-in">
            <h1 className="text-3xl font-bold text-[var(--color-ink)]">
              {greeting}
              {activeMember && <span className="capitalize">, {activeMember}</span>}
            </h1>
            <p className="mt-2 text-[var(--color-ink-muted)]">{tagline}</p>
          </div>
        )}

        {messages.map((msg, i) => {
          const prev = messages[i - 1]
          const next = messages[i + 1]
          const isFirstInGroup = !prev || prev.role !== msg.role
          const isLastInGroup = !next || next.role !== msg.role
          const isUser = msg.role === 'user'
          const isEmptyAssistant =
            !isUser && msg.content.length === 0 && streaming
          const groupGap = isFirstInGroup ? 'mt-2.5' : 'mt-0.5'

          // Assistant replies become one bubble per blank-line-separated beat
          // (texting style). User messages and the typing placeholder are one.
          const chunks = isEmptyAssistant
            ? ['']
            : isUser
              ? [msg.content]
              : splitBubbles(msg.content)

          return (
            <div
              key={msg.id}
              className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} ${groupGap}`}
            >
              {chunks.map((chunk, b) => {
                const lastBubble = b === chunks.length - 1
                const canReply = !isEmptyAssistant && !!chunk
                return (
                  // Swipe right past the threshold to reply to THIS bubble. drag
                  // is x-only and snaps back; touchAction pan-y keeps the list
                  // vertically scrollable.
                  <motion.div
                    key={b}
                    drag={canReply ? 'x' : false}
                    dragConstraints={{ left: 0, right: 0 }}
                    dragElastic={{ left: 0, right: 0.5 }}
                    dragSnapToOrigin
                    onDragEnd={(_e, info) => {
                      if (info.offset.x > 56) setReplyTo(msg.role, chunk)
                    }}
                    className={`max-w-[78%] ${b === 0 ? '' : 'mt-0.5'}`}
                    style={{ touchAction: 'pan-y' }}
                  >
                    <div
                      className={[
                        'px-3.5 py-2 text-[15px] leading-[1.35]',
                        bubbleRadius(
                          msg.role,
                          isFirstInGroup && b === 0,
                          lastBubble && isLastInGroup,
                        ),
                        isUser
                          ? 'bg-[var(--color-imessage-blue)] text-white origin-bottom-right animate-bubble-in-right'
                          : 'bg-[var(--color-bubble-other)] text-[var(--color-ink)] origin-bottom-left animate-bubble-in-left',
                      ].join(' ')}
                      style={{ willChange: 'transform, opacity' }}
                    >
                      {isUser && b === 0 && msg.replyTo?.text && (
                        <div className="mb-1 border-l-2 border-white/40 pl-2 text-[12px] leading-snug text-white/70 line-clamp-2">
                          {msg.replyTo.text}
                        </div>
                      )}
                      {isEmptyAssistant ? (
                        <TypingDots />
                      ) : isUser ? (
                        <p className="whitespace-pre-wrap break-words">{chunk}</p>
                      ) : (
                        <div className="prose prose-sm max-w-none prose-p:my-1 prose-p:leading-snug prose-ul:my-1 prose-ol:my-1 prose-pre:my-2">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {chunk}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </motion.div>
                )
              })}
            </div>
          )
        })}
      </div>

      <div className="px-3 pb-4 pt-2">
        {error && (
          <div className="mb-2 flex items-center justify-between rounded-2xl bg-red-900/30 border border-red-500/30 px-3.5 py-2 text-sm text-red-300 animate-fade-in">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="ml-3 text-red-400 hover:text-red-200"
              aria-label="Dismiss error"
            >
              ✕
            </button>
          </div>
        )}
        {replyTo && (
          <div className="mb-2 flex items-center justify-between rounded-2xl bg-[var(--color-surface)] border border-[var(--color-border)] px-3.5 py-2 animate-fade-in">
            <div className="min-w-0 border-l-2 border-[var(--color-imessage-blue)] pl-2.5">
              <div className="text-[11px] font-medium text-[var(--color-ink-muted)]">
                Replying to {replyTo.role === 'assistant' ? 'advisor' : 'yourself'}
              </div>
              <div className="truncate text-[13px] text-[var(--color-ink)]">{replyTo.text}</div>
            </div>
            <button
              onClick={clearReplyTo}
              aria-label="Cancel reply"
              className="ml-3 shrink-0 text-[var(--color-ink-muted)] hover:text-[var(--color-ink)]"
            >
              ✕
            </button>
          </div>
        )}
        <div className="flex items-end gap-2">
          <div className="flex-1 flex items-end rounded-3xl bg-[var(--color-surface)] border border-[var(--color-border)] pl-4 pr-1.5 py-1.5 focus-within:border-[var(--color-ink-muted)] transition-colors">
            <textarea
              ref={textareaRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Message"
              disabled={streaming && messages.length === 0}
              rows={1}
              className="flex-1 resize-none bg-transparent outline-none text-[16px] leading-[1.35] py-1.5 placeholder:text-[var(--color-ink-muted)] max-h-[120px] text-[var(--color-ink)]"
            />
            <button
              onClick={handleSubmit}
              disabled={!canSend}
              aria-label="Send"
              className={[
                'press-shrink shrink-0 ml-1 mb-0.5 grid place-items-center h-7 w-7 rounded-full',
                canSend
                  ? 'bg-[var(--color-imessage-blue)] text-white hover:bg-[var(--color-imessage-blue-press)]'
                  : 'bg-white/10 text-white/30 cursor-not-allowed',
                'transition-colors duration-150',
              ].join(' ')}
            >
              <SendArrow />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
