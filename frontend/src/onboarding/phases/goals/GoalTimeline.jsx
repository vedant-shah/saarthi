import { motion } from 'motion/react'
import { useOnboardingStore } from '../../../store/onboardingStore'
import { BUCKETS, iconFor } from './goalCatalog'
import { formatINR } from '../../money'
import { PrimaryButton, GhostButton } from '../../ui/buttons'

// Stable fallback, see BucketScreen: a fresh [] inside the selector loops React.
const NO_GOALS = []

// The payoff screen: every goal placed on one quiet vertical timeline.
export function GoalTimeline({ member, onBack }) {
  const goals = useOnboardingStore((s) => s.goals[member.id]) ?? NO_GOALS
  const markPhaseDone = useOnboardingStore((s) => s.markPhaseDone)
  const persistMemberData = useOnboardingStore((s) => s.persistMemberData)
  const openHub = useOnboardingStore((s) => s.openHub)

  const finish = () => {
    markPhaseDone(member.id, 'goals')
    persistMemberData(member.id, 'goals')
    openHub()
  }

  const total = goals.length

  return (
    <div className="mx-auto flex h-full max-w-md flex-col px-5 py-5">
      <div className="shrink-0 text-center">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--color-ink)]">
          {total > 0 ? 'The road ahead' : 'No goals yet'}
        </h1>
        <p className="mt-1 text-[14px] text-[var(--color-ink-muted)]">
          {total > 0
            ? `${total} ${total === 1 ? 'goal' : 'goals'} on the timeline. Your advisor plans around these.`
            : 'That is okay. The advisor will help you find them in chat.'}
        </p>
      </div>

      <div className="relative mt-6 min-h-0 flex-1 overflow-y-auto">
        {total > 0 && (
          <div className="absolute left-[15px] top-1 h-full w-px bg-gradient-to-b from-[var(--accent)] via-[var(--color-border)] to-transparent" />
        )}
        <div className="flex flex-col gap-6 pb-2">
          {BUCKETS.map((bucket, bucketIdx) => {
            const list = goals.filter((g) => g.bucket === bucket.key)
            if (list.length === 0) return null
            return (
              <div key={bucket.key} className="relative">
                <div className="mb-2 flex items-center gap-3">
                  <span className="relative z-10 ml-[10px] h-[11px] w-[11px] shrink-0 rounded-full bg-[var(--accent)]" />
                  <span className="text-[12px] font-semibold uppercase tracking-wider text-[var(--color-ink-muted)]">
                    {bucket.label}
                  </span>
                </div>
                <div className="flex flex-col gap-2 pl-9">
                  {list.map((g, goalIdx) => {
                    const Icon = iconFor(g)
                    return (
                      <motion.div
                        key={g.id}
                        initial={{ opacity: 0, x: 16 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{
                          delay: (bucketIdx * 2 + goalIdx) * 0.07,
                          type: 'spring',
                          stiffness: 320,
                          damping: 28,
                        }}
                        className="flex items-center gap-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)]">
                          <Icon size={17} weight="duotone" className="text-[var(--accent)]" />
                        </span>
                        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-[var(--color-ink)]">
                          {g.title}
                        </span>
                        <span className="shrink-0 text-[13px] tabular-nums text-[var(--color-ink-muted)]">
                          {g.notSure ? 'not sure yet' : g.amount ? formatINR(g.amount) : ''}
                        </span>
                      </motion.div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="flex shrink-0 flex-col gap-2 pb-2 pt-3">
        <PrimaryButton onClick={finish}>Done, back to family</PrimaryButton>
        <GhostButton onClick={onBack}>Add or change goals</GhostButton>
      </div>
    </div>
  )
}
