import { useEffect, useState } from 'react'
import { UsersThree, Gear, X, CaretRight } from '@phosphor-icons/react'
import { ENDPOINTS } from '../lib/api'
import { useOnboardingStore } from '../store/onboardingStore'

// Slide-over settings panel: houses Family setup and the Claude API key.
// The key field is write-only — the saved key is never sent back to the client.
export function SettingsSheet({ onClose }) {
  const openHub = useOnboardingStore((s) => s.openHub)
  const [configured, setConfigured] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('') // '' | 'saved' | 'error'

  useEffect(() => {
    fetch(ENDPOINTS.settingsApiKey)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setConfigured(Boolean(d.configured)) })
      .catch(() => {})
  }, [])

  async function saveKey() {
    const trimmed = apiKey.trim()
    if (!trimmed) return
    setSaving(true)
    setStatus('')
    try {
      const r = await fetch(ENDPOINTS.settingsApiKey, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: trimmed }),
      })
      if (!r.ok) throw new Error('save failed')
      setConfigured(true)
      setApiKey('')
      setStatus('saved')
    } catch {
      setStatus('error')
    } finally {
      setSaving(false)
    }
  }

  function openFamilySetup() {
    onClose()
    openHub()
  }

  return (
    <div className="fixed inset-0 z-30 flex justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative z-10 flex h-full w-full max-w-md flex-col bg-[var(--color-bg)] shadow-xl">
        <header className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
          <div className="flex items-center gap-2 text-[15px] font-semibold text-[var(--color-ink)]">
            <Gear size={18} weight="bold" />
            Settings
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="press-shrink rounded-full p-1 text-[var(--color-ink-muted)] transition-colors hover:text-[var(--color-ink)]"
          >
            <X size={20} weight="bold" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          <button
            onClick={openFamilySetup}
            className="press-shrink flex w-full items-center gap-3 rounded-xl border border-[var(--color-border)] px-4 py-3 text-left transition-colors hover:border-[var(--color-ink-muted)]"
          >
            <UsersThree size={20} weight="bold" className="text-[var(--color-ink)]" />
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-medium text-[var(--color-ink)]">Family setup</div>
              <div className="text-[12px] text-[var(--color-ink-muted)]">
                Add members and complete onboarding
              </div>
            </div>
            <CaretRight size={16} weight="bold" className="text-[var(--color-ink-muted)]" />
          </button>

          <div className="mt-6">
            <label htmlFor="claude-api-key" className="block text-[13px] font-medium text-[var(--color-ink)]">
              Claude API key
            </label>
            <p className="mt-1 text-[12px] text-[var(--color-ink-muted)]">
              {configured
                ? 'A key is saved. Enter a new one to replace it.'
                : 'Not set. The app falls back to the server key if one exists.'}
            </p>
            <input
              id="claude-api-key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={configured ? '•••• saved' : 'sk-ant-...'}
              autoComplete="off"
              className="mt-2 w-full rounded-lg border border-[var(--color-border)] bg-transparent px-3 py-2 text-[14px] text-[var(--color-ink)] outline-none focus:border-[var(--color-ink-muted)]"
            />
            <button
              onClick={saveKey}
              disabled={saving || !apiKey.trim()}
              className="press-shrink mt-3 w-full rounded-lg bg-[var(--color-ink)] px-4 py-2 text-[14px] font-medium text-[var(--color-bg)] disabled:opacity-40"
            >
              {saving ? 'Saving…' : 'Save key'}
            </button>
            {status === 'saved' && <p className="mt-2 text-[12px] text-green-500">Saved.</p>}
            {status === 'error' && (
              <p className="mt-2 text-[12px] text-red-500">Could not save. Try again.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
