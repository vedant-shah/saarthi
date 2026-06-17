import { ChatCircleText } from '@phosphor-icons/react'
import { useOnboardingStore } from '../../../store/onboardingStore'
import { Whisper } from '../../ui/Whisper'
import { PrimaryButton } from '../../ui/buttons'

const EMPTY_CHECK = {}

const PLACEHOLDER =
  'For example: Dad retires in 2027. We send money home every month. ' +
  'I already hold some shares an uncle suggested years ago.'

// The open mic at the very end: anything the advisor should know, verbatim.
export function FinalNoteScreen({ member, onFinish }) {
  const check = useOnboardingStore((s) => s.checks[member.id]) ?? EMPTY_CHECK
  const updateCheck = useOnboardingStore((s) => s.updateCheck)
  const markPhaseDone = useOnboardingStore((s) => s.markPhaseDone)
  const persistMemberData = useOnboardingStore((s) => s.persistMemberData)

  const finish = () => {
    markPhaseDone(member.id, 'check')
    persistMemberData(member.id, 'check')
    onFinish()
  }

  return (
    <div className="mx-auto flex h-full max-w-md flex-col gap-5 px-5 py-5">
      <div>
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[var(--accent-soft)]">
            <ChatCircleText size={22} weight="duotone" className="text-[var(--accent)]" />
          </span>
          <h1 className="text-2xl font-bold tracking-tight text-[var(--color-ink)]">
            Anything else?
          </h1>
        </div>
        <p className="mt-3 text-[15px] leading-relaxed text-[var(--color-ink-muted)]">
          {member.isSelf
            ? 'Anything your advisor should know that the taps could not capture.'
            : `Anything about ${member.name} the advisor should know that the taps could not capture.`}
        </p>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <textarea
          value={check.note ?? ''}
          onChange={(e) => updateCheck(member.id, { note: e.target.value })}
          placeholder={PLACEHOLDER}
          rows={6}
          aria-label="Anything else your advisor should know"
          className="w-full resize-none rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 text-[15px] leading-relaxed text-[var(--color-ink)] outline-none transition-colors placeholder:text-[var(--color-ink-muted)] focus:border-[var(--accent)]"
        />
        <Whisper>
          In your own words, any language. Completely fine to skip if nothing comes to
          mind.
        </Whisper>
      </div>

      <div className="mt-auto pb-2">
        <PrimaryButton onClick={finish}>
          {check.note?.trim() ? 'Finish' : 'Nothing to add, finish'}
        </PrimaryButton>
      </div>
    </div>
  )
}
