import { AnimatePresence, motion } from 'motion/react'
import { Coins, Umbrella } from '@phosphor-icons/react'
import { useOnboardingStore } from '../../../store/onboardingStore'
import { ASSET_CLASSES } from './moneyCatalog'
import { FinRow, AmountControl } from './FinRow'
import { DocumentImport } from './DocumentImport'
import { formatINR } from '../../money'
import { pastelVars } from '../../theme'
import { Chip } from '../../ui/Chip'
import { PrimaryButton } from '../../ui/buttons'

const EMPTY_FIN = {}
const NO_ITEMS = []

const BAR_PASTELS = ['mint', 'peach', 'lavender', 'rose', 'sky', 'butter']

export function SavingsScreen({ member, onNext }) {
  const fin = useOnboardingStore((s) => s.finances[member.id]) ?? EMPTY_FIN
  const updateFinances = useOnboardingStore((s) => s.updateFinances)
  const assets = fin.assets ?? NO_ITEMS

  const setAssets = (next) => updateFinances(member.id, { assets: next })
  const selectedKeys = new Set(assets.map((a) => a.key))

  const toggle = (cls) => {
    if (selectedKeys.has(cls.key)) {
      setAssets(assets.filter((a) => a.key !== cls.key))
    } else {
      setAssets([...assets, { key: cls.key, label: cls.label, amount: null }])
    }
  }

  const update = (key, fields) =>
    setAssets(assets.map((a) => (a.key === key ? { ...a, ...fields } : a)))

  // Remove a single asset row by key — works for chip-selected classes and for
  // rows imported from a document (whose key may not match any chip class).
  const removeAsset = (key) => setAssets(assets.filter((a) => a.key !== key))

  // The member's stated monthly outflow already carries its own scope: a
  // household payer's number includes the home, others' covers just themselves.
  const spendValue = fin.spend ?? fin.personalSpend ?? null
  const emergencyMonths =
    spendValue && fin.emergencyFund ? fin.emergencyFund / spendValue : null
  const burnLabel =
    fin.spendScope === 'all'
      ? `everything that goes out through ${member.isSelf ? 'you' : member.name}`
      : member.isSelf
        ? 'your own spending'
        : `${member.name}'s own spending`

  return (
    <div className="mx-auto flex h-full max-w-md flex-col px-5 py-5">
      <div className="shrink-0">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--color-ink)]">
          What you&apos;ve saved or own
        </h1>
        <p className="mt-1 text-[14px] text-[var(--color-ink-muted)]">
          {member.isSelf ? 'Yours' : `${member.name}'s`}. Tap what applies, estimates are
          welcome.
        </p>
      </div>

      <div className="mt-4 shrink-0">
        <DocumentImport member={member} />
      </div>

      <div className="mt-5 flex shrink-0 flex-wrap gap-2">
        {ASSET_CLASSES.map((c) => (
          <Chip
            key={c.key}
            selected={selectedKeys.has(c.key)}
            onClick={() => toggle(c)}
            className="flex items-center gap-1.5"
          >
            <c.Icon size={15} weight={selectedKeys.has(c.key) ? 'fill' : 'regular'} />
            {c.label}
          </Chip>
        ))}
      </div>

      <div className="mt-4 flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-1">
        <AssetBar assets={assets} />

        <div className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {assets.map((asset) => {
              const cls = ASSET_CLASSES.find((c) => c.key === asset.key)
              return (
                <FinRow
                  key={asset.key}
                  Icon={cls?.Icon ?? Coins}
                  label={asset.label}
                  summary={asset.amount != null ? formatINR(asset.amount) : 'roughly?'}
                  onRemove={() => removeAsset(asset.key)}
                >
                  <AmountControl
                    label="Rough current value"
                    value={asset.amount}
                    defaultValue={cls?.defaultAmount ?? 100000}
                    min={10000}
                    max={200000000}
                    onChange={(v) => update(asset.key, { amount: v })}
                  />
                </FinRow>
              )
            })}
          </AnimatePresence>
        </div>

        <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3.5">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)]">
              <Umbrella size={18} weight="duotone" className="text-[var(--accent)]" />
            </span>
            <span className="min-w-0 flex-1 text-[14px] font-semibold text-[var(--color-ink)]">
              Set aside for emergencies?
            </span>
          </div>
          <AmountControl
            label="Money you could reach tomorrow if something went wrong"
            value={fin.emergencyFund ?? null}
            defaultValue={100000}
            min={10000}
            max={10000000}
            onChange={(v) => updateFinances(member.id, { emergencyFund: v })}
          />
          {emergencyMonths != null && (
            <p className="mt-1 text-[12px] font-medium text-[var(--accent)]">
              Enough to cover about{' '}
              {emergencyMonths >= 10
                ? Math.round(emergencyMonths)
                : Math.round(emergencyMonths * 10) / 10}{' '}
              months of {burnLabel}.
            </p>
          )}
        </div>

      </div>

      <div className="shrink-0 pb-2 pt-3">
        <PrimaryButton onClick={onNext}>
          {assets.length > 0 || fin.emergencyFund ? 'Continue' : 'Nothing to add, next'}
        </PrimaryButton>
      </div>
    </div>
  )
}

// The composition strip: what you own, assembling live as values are set.
function AssetBar({ assets }) {
  const withAmounts = assets.filter((a) => a.amount != null)
  if (withAmounts.length === 0) return null
  const total = withAmounts.reduce((sum, a) => sum + a.amount, 0)

  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="shrink-0">
      <div className="flex items-baseline justify-between">
        <span className="text-[12px] text-[var(--color-ink-muted)]">All together</span>
        <span className="text-[14px] font-semibold tabular-nums text-[var(--color-ink)]">
          {formatINR(total)}
        </span>
      </div>
      <div className="mt-1.5 flex h-2.5 w-full overflow-hidden rounded-full">
        {withAmounts.map((a, i) => {
          const pastel = pastelVars(BAR_PASTELS[i % BAR_PASTELS.length])
          return (
            <div
              key={a.key}
              className="h-full transition-[width] duration-300"
              style={{ width: `${(a.amount / total) * 100}%`, background: pastel.solid }}
            />
          )
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        {withAmounts.map((a, i) => {
          const pastel = pastelVars(BAR_PASTELS[i % BAR_PASTELS.length])
          return (
            <span key={a.key} className="flex items-center gap-1 text-[11px] text-[var(--color-ink-muted)]">
              <span className="h-2 w-2 rounded-full" style={{ background: pastel.solid }} />
              {a.label}
            </span>
          )
        })}
      </div>
    </motion.div>
  )
}
