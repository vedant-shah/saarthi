import { useRef, useState } from 'react'
import { CheckCircle, LockSimple, Paperclip, SpinnerGap, X } from '@phosphor-icons/react'
import { useOnboardingStore } from '../../../store/onboardingStore'
import { ENDPOINTS } from '../../../lib/api'
import { ASSET_CLASSES } from './moneyCatalog'
import { formatINR } from '../../money'
import { PrimaryButton, GhostButton } from '../../ui/buttons'

const ACCEPT = '.csv,.xlsx,.pdf'
const NO_ASSETS = []

// Upload one or more statements (CAS PDF, broker CSV, portfolio XLSX). Each file
// is read by the model (passwords prompted per file); the holdings from all files
// are then merged by a grouping pass that knows a CAS is consolidated, so the same
// fund seen twice is collapsed rather than double-counted. The merged list is shown
// for review; on confirm we REPLACE each asset-class slider with the grouped total
// and log one dated snapshot per source statement. Nothing is saved until confirm.
export function DocumentImport({ member }) {
  const updateFinances = useOnboardingStore((s) => s.updateFinances)
  const currentAssets = useOnboardingStore((s) => s.finances[member.id]?.assets) ?? NO_ASSETS

  const fileRef = useRef(null)
  const queueRef = useRef([]) // files still to extract
  const resultsRef = useRef([]) // { filename, document_type, statement_date, holdings }

  const [status, setStatus] = useState('idle') // idle | working | password | review | done | error
  const [busyText, setBusyText] = useState('')
  const [error, setError] = useState('')
  const [holdings, setHoldings] = useState([]) // grouped, shown for review
  const [editing, setEditing] = useState(null)
  const [currentFile, setCurrentFile] = useState(null) // file awaiting a password
  const [password, setPassword] = useState('')
  const [fileCount, setFileCount] = useState(0)

  const who = member.isSelf ? 'your' : `${member.name}'s`

  // Extract one file. Returns { needPassword } for an encrypted PDF, or { result }.
  const extractFile = async (file, pw) => {
    const body = new FormData()
    body.append('file', file)
    if (pw) body.append('password', pw)
    // No Content-Type header — the browser sets the multipart boundary.
    const res = await fetch(ENDPOINTS.onboardingExtractDocument, {
      method: 'POST',
      headers: { 'X-Member-Id': member.id },
      body,
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const code = data?.detail?.code
      if (res.status === 422 && code) {
        return { needPassword: true, wrongPassword: code === 'pdf_password_wrong' }
      }
      throw new Error(
        typeof data.detail === 'string' ? data.detail : `Could not read ${file.name}.`,
      )
    }
    const data = await res.json()
    return {
      result: {
        filename: file.name,
        document_type: data.document_type ?? 'other',
        statement_date: data.statement_date ?? null,
        holdings: data.holdings ?? [],
      },
    }
  }

  // Walk the queue, pausing for a password whenever an encrypted PDF turns up.
  const runQueue = async () => {
    setStatus('working')
    setError('')
    while (queueRef.current.length) {
      const file = queueRef.current[0]
      setBusyText(`Reading ${file.name}…`)
      try {
        const out = await extractFile(file, null)
        if (out.needPassword) {
          setCurrentFile(file)
          setPassword('')
          setStatus('password')
          setError('')
          return // resume from unlock()
        }
        resultsRef.current.push(out.result)
        queueRef.current.shift()
      } catch (err) {
        setStatus('error')
        setError(err.message || 'Something went wrong reading the file.')
        return
      }
    }
    await finishExtraction()
  }

  const unlock = async () => {
    const file = currentFile
    if (!file || !password) return
    setStatus('working')
    setBusyText(`Unlocking ${file.name}…`)
    try {
      const out = await extractFile(file, password)
      if (out.needPassword) {
        setStatus('password')
        setError('That password did not work. Try again.')
        setPassword('')
        return
      }
      resultsRef.current.push(out.result)
      queueRef.current.shift()
      setCurrentFile(null)
      await runQueue()
    } catch (err) {
      setStatus('error')
      setError(err.message || 'Something went wrong reading the file.')
    }
  }

  // All files read: merge their holdings into one deduped list for review.
  const finishExtraction = async () => {
    const results = resultsRef.current
    setFileCount(results.length)
    const allHoldings = results.flatMap((r) => r.holdings ?? [])
    if (allHoldings.length === 0) {
      setStatus('error')
      setError('Could not find any holdings in those files. You can add them by hand above.')
      return
    }
    setBusyText('Merging holdings across your statements…')
    try {
      const res = await fetch(ENDPOINTS.onboardingGroupHoldings, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Member-Id': member.id },
        body: JSON.stringify({
          sources: results.map((r) => ({
            document_type: r.document_type,
            statement_date: r.statement_date,
            holdings: r.holdings,
          })),
        }),
      })
      if (!res.ok) throw new Error('group failed')
      const data = await res.json()
      setHoldings(data.holdings?.length ? data.holdings : allHoldings)
    } catch {
      // If grouping fails, fall back to the raw merge so the user isn't blocked.
      setHoldings(allHoldings)
    }
    setStatus('review')
  }

  const onFiles = (e) => {
    const files = Array.from(e.target.files || [])
    e.target.value = '' // let the same files be picked again later
    if (!files.length) return
    queueRef.current = files
    resultsRef.current = []
    setCurrentFile(null)
    setPassword('')
    setHoldings([])
    setEditing(null)
    runQueue()
  }

  const editHolding = (i, patch) =>
    setHoldings(holdings.map((h, idx) => (idx === i ? { ...h, ...patch } : h)))

  const removeHolding = (i) => setHoldings(holdings.filter((_, idx) => idx !== i))

  // Best-effort dated snapshot: the slider values still persist via the normal
  // money-phase save, so a failed snapshot only loses that dated history entry.
  const saveSnapshot = (items, date) => {
    fetch(ENDPOINTS.onboardingPortfolioSnapshot, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Member-Id': member.id },
      body: JSON.stringify({ holdings: items, statement_date: date }),
    }).catch(() => {
      /* best-effort */
    })
  }

  const confirm = () => {
    // Sum the grouped holdings per class and REPLACE each class's slider with that
    // total — the documents are authoritative; the sliders were estimates.
    const totals = {}
    for (const h of holdings) {
      const amount = Number(h.amount)
      if (!h.label?.trim() || !(amount > 0)) continue
      const key = h.asset_class || 'other'
      totals[key] = (totals[key] ?? 0) + amount
    }
    const byKey = new Map(currentAssets.map((a) => [a.key, { ...a }]))
    for (const [key, amount] of Object.entries(totals)) {
      const cls = ASSET_CLASSES.find((c) => c.key === key)
      byKey.set(key, { key, label: cls?.label ?? 'Other holdings', amount })
    }
    updateFinances(member.id, { assets: Array.from(byKey.values()) })

    // One dated snapshot per source statement, faithful to each document's date.
    for (const r of resultsRef.current) {
      if (r.holdings?.length) saveSnapshot(r.holdings, r.statement_date)
    }

    setHoldings([])
    setEditing(null)
    setStatus('done')
    setError(Object.keys(totals).length === 0 ? 'Nothing to add.' : '')
  }

  const reset = () => {
    queueRef.current = []
    resultsRef.current = []
    setHoldings([])
    setEditing(null)
    setCurrentFile(null)
    setPassword('')
    setFileCount(0)
    setStatus('idle')
    setError('')
  }

  return (
    <div className="rounded-2xl border border-dashed border-[var(--color-border)] p-3.5">
      <input
        ref={fileRef}
        type="file"
        accept={ACCEPT}
        multiple
        onChange={onFiles}
        className="hidden"
        aria-hidden="true"
      />

      {(status === 'idle' || status === 'error') && (
        <div className="flex items-start gap-3">
          <Paperclip size={18} className="mt-0.5 shrink-0 text-[var(--color-ink-muted)]" />
          <div className="min-w-0 flex-1">
            <p className="text-[13px] text-[var(--color-ink-muted)]">
              Have statements? Upload {who} CAS, broker exports, or portfolio sheets
              &mdash; you can pick several at once &mdash; and we&apos;ll pull the
              holdings out and fill in the amounts below.
            </p>
            {status === 'error' && (
              <p className="mt-1 text-[12px] font-medium text-[var(--color-danger,#c0392b)]">
                {error}
              </p>
            )}
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="mt-2 inline-block rounded-full bg-[var(--accent-soft)] px-3 py-1.5 text-[12px] font-semibold text-[var(--accent)]"
            >
              {status === 'error' ? 'Try again' : 'Upload CSV, XLSX or PDF'}
            </button>
          </div>
        </div>
      )}

      {status === 'working' && (
        <div className="flex items-center gap-3 py-1">
          <SpinnerGap size={18} className="shrink-0 animate-spin text-[var(--accent)]" />
          <p className="text-[13px] text-[var(--color-ink-muted)]">
            {busyText || 'Reading your statements…'}
          </p>
        </div>
      )}

      {status === 'password' && (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-start gap-3">
            <LockSimple size={18} className="mt-0.5 shrink-0 text-[var(--color-ink-muted)]" />
            <p className="min-w-0 flex-1 text-[13px] text-[var(--color-ink-muted)]">
              {currentFile?.name ? `"${currentFile.name}" is` : 'That PDF is'} password
              protected. Enter its password to unlock it &mdash; a CAS is usually
              locked with your PAN or a password the provider emailed you.
            </p>
          </div>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && unlock()}
            placeholder="PDF password"
            aria-label="PDF password"
            autoFocus
            className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-[13px] text-[var(--color-ink)] outline-none focus:border-[var(--accent)]"
          />
          {error && (
            <p className="text-[12px] font-medium text-[var(--color-danger,#c0392b)]">{error}</p>
          )}
          <div className="flex flex-col gap-1.5">
            <PrimaryButton onClick={unlock} disabled={!password}>
              Unlock and read
            </PrimaryButton>
            <GhostButton onClick={reset}>Cancel</GhostButton>
          </div>
        </div>
      )}

      {status === 'review' && (
        <div className="flex flex-col gap-2.5">
          <p className="text-[13px] font-semibold text-[var(--color-ink)]">
            Found {holdings.length} {holdings.length === 1 ? 'holding' : 'holdings'}
            {fileCount > 1 ? ` across ${fileCount} files` : ''}. Tap any line to fix it.
          </p>
          <div className="flex flex-col gap-1.5">
            {holdings.map((h, i) =>
              editing === i ? (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={h.label}
                    onChange={(e) => editHolding(i, { label: e.target.value })}
                    aria-label="Holding name"
                    className="min-w-0 flex-1 rounded-lg border border-[var(--accent)] bg-[var(--color-surface)] px-2 py-1 text-[13px] text-[var(--color-ink)] outline-none"
                  />
                  <input
                    value={h.amount}
                    onChange={(e) => editHolding(i, { amount: e.target.value.replace(/[^0-9.]/g, '') })}
                    inputMode="decimal"
                    aria-label="Holding value in rupees"
                    className="w-24 rounded-lg border border-[var(--accent)] bg-[var(--color-surface)] px-2 py-1 text-right text-[13px] tabular-nums text-[var(--color-ink)] outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setEditing(null)}
                    className="shrink-0 text-[12px] font-semibold text-[var(--accent)]"
                  >
                    Done
                  </button>
                </div>
              ) : (
                <div key={i} className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditing(i)}
                    className="min-w-0 flex-1 text-left text-[13px] text-[var(--color-ink)]"
                  >
                    <span className="font-medium">{h.label}</span>
                    <span className="text-[var(--color-ink-muted)]">
                      {' '}
                      &mdash; {Number(h.amount) > 0 ? formatINR(Number(h.amount)) : 'no value'}
                    </span>
                    {h.sources?.length > 0 && (
                      <span className="text-[11px] text-[var(--color-ink-muted)]">
                        {' '}
                        &middot; from {h.sources.join(', ')}
                      </span>
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => removeHolding(i)}
                    aria-label={`Remove ${h.label}`}
                    className="shrink-0 text-[var(--color-ink-muted)]"
                  >
                    <X size={14} />
                  </button>
                </div>
              ),
            )}
          </div>
          <div className="flex flex-col gap-1.5 pt-1">
            <PrimaryButton onClick={confirm} disabled={holdings.length === 0}>
              Add to {member.isSelf ? 'my' : 'their'} savings
            </PrimaryButton>
            <GhostButton onClick={reset}>Discard</GhostButton>
          </div>
        </div>
      )}

      {status === 'done' && (
        <div className="flex items-center gap-3 py-1">
          <CheckCircle size={18} weight="fill" className="shrink-0 text-[var(--accent)]" />
          <p className="flex-1 text-[13px] text-[var(--color-ink)]">
            {error
              ? error
              : 'Added to the savings below. Adjust any amount there if it looks off.'}
          </p>
          <button
            type="button"
            onClick={reset}
            className="shrink-0 text-[12px] font-semibold text-[var(--accent)]"
          >
            Add more
          </button>
        </div>
      )}
    </div>
  )
}
