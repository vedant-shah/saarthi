import { useOnboardingStore } from '../../../store/onboardingStore'
import { AmountControl } from './FinRow'
import { Segmented } from '../../ui/Segmented'
import { Whisper } from '../../ui/Whisper'
import { PrimaryButton } from '../../ui/buttons'

const EMPTY_FIN = {}

const YES_NO = [
  { value: true, label: 'Yes' },
  { value: false, label: 'No' },
]

export function ProtectionScreen({ member }) {
  const fin = useOnboardingStore((s) => s.finances[member.id]) ?? EMPTY_FIN
  const updateFinances = useOnboardingStore((s) => s.updateFinances)
  const markPhaseDone = useOnboardingStore((s) => s.markPhaseDone)
  const persistMemberData = useOnboardingStore((s) => s.persistMemberData)
  const openHub = useOnboardingStore((s) => s.openHub)

  const health = fin.health ?? {}
  const term = fin.term ?? {}
  const who = member.isSelf ? 'you' : member.name

  const finish = () => {
    markPhaseDone(member.id, 'money')
    persistMemberData(member.id, 'money')
    openHub()
  }

  return (
    <div className="mx-auto flex h-full max-w-md flex-col gap-6 overflow-y-auto px-5 py-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[var(--color-ink)]">
          The safety net
        </h1>
        <p className="mt-1 text-[14px] text-[var(--color-ink-muted)]">
          Two quick questions, yes or no.
        </p>
      </div>

      <div>
        <label className="text-sm font-medium text-[var(--color-ink)]">
          If {who} landed in hospital, would an insurance pay?
        </label>
        <div className="mt-1.5">
          <Segmented
            options={YES_NO}
            value={health.covered ?? null}
            onChange={(covered) =>
              updateFinances(member.id, { health: { ...health, covered } })
            }
          />
        </div>
        <Whisper>A policy from work counts.</Whisper>
        {health.covered === true && (
          <div className="mt-3">
            <AmountControl
              label="Rough cover amount"
              value={health.cover ?? null}
              defaultValue={500000}
              min={100000}
              max={20000000}
              onChange={(cover) =>
                updateFinances(member.id, { health: { ...health, cover } })
              }
            />
          </div>
        )}
      </div>

      {member.earns && (
        <div>
          <label className="text-sm font-medium text-[var(--color-ink)]">
            Is there a term plan that pays the family if something happens to {who}?
          </label>
          <div className="mt-1.5">
            <Segmented
              options={YES_NO}
              value={term.covered ?? null}
              onChange={(covered) =>
                updateFinances(member.id, { term: { ...term, covered } })
              }
            />
          </div>
          <Whisper>
            Term plans are pure protection. Endowment or money-back policies are not
            this.
          </Whisper>
          {term.covered === true && (
            <div className="mt-3">
              <AmountControl
                label="Rough cover amount"
                value={term.cover ?? null}
                defaultValue={5000000}
                min={500000}
                max={100000000}
                onChange={(cover) =>
                  updateFinances(member.id, { term: { ...term, cover } })
                }
              />
            </div>
          )}
        </div>
      )}

      <div className="mt-auto pb-2">
        <PrimaryButton onClick={finish}>Finish the money picture</PrimaryButton>
      </div>
    </div>
  )
}
