import { useEffect, useState } from 'react'
import { Gear } from '@phosphor-icons/react'
import { ENDPOINTS } from './lib/api'
import { useChatStore } from './store/chatStore'
import { useOnboardingStore } from './store/onboardingStore'
import { MemberSwitcher } from './components/MemberSwitcher'
import { Chat } from './components/Chat'
import { OnboardingNudge } from './components/OnboardingNudge'
import { SettingsSheet } from './components/SettingsSheet'
import { OnboardingRoot } from './onboarding/OnboardingRoot'

function App() {
  const setMembers = useChatStore((s) => s.setMembers)
  const setActiveMember = useChatStore((s) => s.setActiveMember)
  const activeMember = useChatStore((s) => s.activeMember)
  const onboardingRoute = useOnboardingStore((s) => s.route)
  const openHub = useOnboardingStore((s) => s.openHub)
  const hydrateFromBackend = useOnboardingStore((s) => s.hydrateFromBackend)

  useEffect(() => {
    hydrateFromBackend()
  }, [])

  useEffect(() => {
    fetch(ENDPOINTS.members)
      .then((r) => r.json())
      .then(({ members }) => {
        setMembers(members)
        // Drop a stale active id (e.g. a wiped/renamed member) so we never
        // chat as someone who no longer exists.
        if (activeMember && !members.includes(activeMember)) {
          setActiveMember(members[0] ?? null)
        } else if (!activeMember && members.length > 0) {
          setActiveMember(members[0])
        }
        // No family in the system yet: nothing to do but set up, so always drop
        // straight into the hub (every load, including refresh), until at least
        // one member exists.
        if (members.length === 0) {
          openHub()
        }
      })
      .catch(() => {})
  }, [])

  // Shared invite links (?onboard=<member>) land straight in the family hub.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).has('onboard')) openHub()
  }, [])

  // Pin the app to the visual viewport. h-dvh does not shrink when the mobile
  // keyboard opens (it overlays), so the input gets shoved off-screen. We fix the
  // app to the viewport and drive BOTH its height and its top offset from
  // visualViewport: height shrinks the flex column (chat area contracts, input
  // stays just above the keyboard), and offsetTop counters the scroll iOS does
  // when the keyboard appears (without it the app drifts and leaves a gap). No-op
  // on browsers without the API (falls back to h-dvh via the className).
  const [settingsOpen, setSettingsOpen] = useState(false)

  const [viewport, setViewport] = useState(null)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const sync = () => setViewport({ top: vv.offsetTop, height: vv.height })
    sync()
    vv.addEventListener('resize', sync)
    vv.addEventListener('scroll', sync)
    return () => {
      vv.removeEventListener('resize', sync)
      vv.removeEventListener('scroll', sync)
    }
  }, [])

  if (onboardingRoute) {
    return <OnboardingRoot />
  }

  return (
    <div
      className="flex flex-col fixed inset-x-0 top-0 mx-auto h-dvh max-w-md bg-[var(--color-bg)]"
      style={viewport ? { top: `${viewport.top}px`, height: `${viewport.height}px` } : undefined}
    >
      <header className="sticky top-0 z-10 grid grid-cols-[auto_1fr_auto] items-center gap-2 px-3 py-2.5 border-b border-[var(--color-border)] bg-[var(--color-bg)] shrink-0">
        <div className="justify-self-start">
          <MemberSwitcher />
        </div>
        <div className="min-w-0 text-center leading-tight">
          <div className="truncate text-[15px] font-semibold text-[var(--color-ink)]">
            Saarthi
          </div>
        </div>
        <div className="justify-self-end">
          <button
            onClick={() => setSettingsOpen(true)}
            aria-label="Settings"
            className="press-shrink flex shrink-0 items-center rounded-full border border-[var(--color-border)] p-1.5 text-[var(--color-ink-muted)] transition-colors hover:text-[var(--color-ink)]"
          >
            <Gear size={18} weight="bold" />
          </button>
        </div>
      </header>
      <OnboardingNudge key={activeMember} />
      <main className="flex-1 overflow-hidden">
        <Chat />
      </main>
      {settingsOpen && <SettingsSheet onClose={() => setSettingsOpen(false)} />}
    </div>
  )
}

export default App
