import { create } from 'zustand'
import { ENDPOINTS } from '../lib/api'

// Onboarding draft, mirrored to localStorage. Identity is also persisted to the
// backend at the end of the "who" phase via persistRoster; money/goals stay in
// the draft until their own persistence round.

const STORAGE_KEY = 'onboardingDraft'

export const PHASES = ['who', 'goals', 'money', 'check']

const EMPTY_DRAFT = {
  household: { city: '', spend: null, whoPays: [] },
  members: [], // { id, name, relationship, age, earns, occupation, livesElsewhere, isSelf, moneyComfort, supports, supportMonthly }
  // supports: ids of the members THIS person financially provides for (their
  // dependents, captured explicitly, never inferred from earning status).
  // supportMonthly: rough total monthly support amount (money; persists later).
  progress: {}, // memberId -> { goals: bool, money: bool, check: bool }
  goals: {}, // memberId -> [ { id, title, bucket, suggestionKey, amount, notSure } ]
  // memberId -> { incomes: [{key,label,amount,cadence}], loans: [{key,label,emi,remaining}],
  //               assets: [{key,label,amount}], emergencyFund, health: {covered,cover},
  //               term: {covered,cover} }
  finances: {},
  checks: {}, // memberId -> { answers: {scenarioKey: optionKey}, note: '' }
  whoDone: false,
}

const newGoalId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`

const readDraft = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...EMPTY_DRAFT, ...JSON.parse(raw) } : EMPTY_DRAFT
  } catch {
    return EMPTY_DRAFT
  }
}

const writeDraft = (draft) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draft))
  } catch {
    /* ignore, localStorage unavailable (private mode, SSR, etc.) */
  }
}

const slugify = (name) =>
  name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '') || 'member'

const uniqueId = (name, members) => {
  const base = slugify(name)
  let id = base
  let n = 2
  while (members.some((m) => m.id === id)) {
    id = `${base}-${n}`
    n += 1
  }
  return id
}

// Apply a patch, then mirror the persisted slice of state to localStorage.
const persist = (set, get, patch) => {
  set(patch)
  const { household, members, progress, goals, finances, checks, whoDone } = get()
  writeDraft({ household, members, progress, goals, finances, checks, whoDone })
}

export const useOnboardingStore = create((set, get) => ({
  ...readDraft(),

  // Navigation (session-only, not persisted).
  route: null, // null | 'hub' | 'phase'
  activePhase: null, // one of PHASES while route === 'phase'
  activeMemberId: null,

  openHub: () => set({ route: 'hub', activePhase: null, activeMemberId: null }),

  openPhase: (phase, memberId = null) =>
    set({ route: 'phase', activePhase: phase, activeMemberId: memberId }),

  exitOnboarding: () =>
    set({ route: null, activePhase: null, activeMemberId: null }),

  addMember: (fields) => {
    const members = get().members
    const member = {
      earns: false,
      occupation: '',
      livesElsewhere: false,
      isSelf: false,
      moneyComfort: null,
      supports: [],
      supportMonthly: null,
      ...fields,
      id: uniqueId(fields.name, members),
    }
    persist(set, get, { members: [...members, member] })
    return member.id
  },

  updateMember: (id, fields) => {
    const members = get().members.map((m) =>
      m.id === id ? { ...m, ...fields } : m,
    )
    persist(set, get, { members })
  },

  removeMember: (id) => {
    // Drop the member, and strip them from anyone who listed them as a dependent.
    const members = get()
      .members.filter((m) => m.id !== id)
      .map((m) =>
        m.supports?.includes(id)
          ? { ...m, supports: m.supports.filter((d) => d !== id) }
          : m,
      )
    const progress = { ...get().progress }
    delete progress[id]
    const goals = { ...get().goals }
    delete goals[id]
    const finances = { ...get().finances }
    delete finances[id]
    const checks = { ...get().checks }
    delete checks[id]
    const whoPays = get().household.whoPays.filter((m) => m !== id)
    persist(set, get, {
      members,
      progress,
      goals,
      finances,
      checks,
      household: { ...get().household, whoPays },
    })
  },

  setHousehold: (fields) => {
    persist(set, get, { household: { ...get().household, ...fields } })
  },

  markWhoDone: () => persist(set, get, { whoDone: true }),

  // Persist the family roster (identity) to the backend, then adopt the
  // canonical member ids it returns: re-key every member id, their `supports`
  // lists, and the per-member maps (progress/goals/finances/checks) + whoPays.
  // Best-effort: a failed POST leaves the local draft intact to retry. Returns
  // { self: <canonical self id> } on success, else null.
  persistRoster: async () => {
    const members = get().members
    if (members.length === 0) return null
    const payload = {
      members: members.map((m) => ({
        id: m.id,
        name: m.name,
        relationship: m.isSelf ? 'self' : m.relationship,
        age: m.age,
        earns: m.earns,
        occupation: m.occupation,
        livesElsewhere: m.livesElsewhere,
        isSelf: m.isSelf,
        moneyComfort: m.moneyComfort,
      })),
    }
    let data
    try {
      const r = await fetch(ENDPOINTS.onboardingRoster, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!r.ok) return null
      data = await r.json()
    } catch {
      return null
    }
    // Response members are in request order; map old id -> canonical id.
    const idMap = {}
    members.forEach((m, i) => {
      const canonical = data.members?.[i]?.id
      if (canonical) idMap[m.id] = canonical
    })
    const remap = (id) => idMap[id] ?? id
    const rekey = (obj) =>
      Object.fromEntries(Object.entries(obj).map(([k, v]) => [remap(k), v]))
    const { progress, goals, finances, checks, household } = get()
    persist(set, get, {
      members: members.map((m) => ({
        ...m,
        id: remap(m.id),
        supports: (m.supports ?? []).map(remap),
      })),
      progress: rekey(progress),
      goals: rekey(goals),
      finances: rekey(finances),
      checks: rekey(checks),
      household: { ...household, whoPays: household.whoPays.map(remap) },
    })
    return { self: data.self }
  },

  // Persist one member's onboarding data to the backend (best-effort). With a
  // `phase` ('goals' | 'money' | 'check') only that phase's slice is sent, so
  // each phase lands on disk as it completes; with no phase the full bundle is
  // sent (a final safety flush). Runs after the roster created their dir; a
  // failed POST leaves the draft to retry. The backend writes each slice
  // idempotently, so partial sends and re-sends are safe.
  persistMemberData: async (memberId, phase = null) => {
    const member = get().members.find((m) => m.id === memberId)
    const finances = get().finances[memberId] ?? {}
    const goals = get().goals[memberId] ?? []
    const checks = get().checks[memberId] ?? {}
    const supportMonthly = member?.supportMonthly ?? null

    let payload
    if (phase === 'goals') payload = { goals }
    else if (phase === 'money') payload = { finances, supportMonthly }
    else if (phase === 'check') payload = { checks }
    else payload = { finances, goals, checks, supportMonthly }

    try {
      await fetch(ENDPOINTS.onboardingMemberData, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Member-Id': memberId },
        body: JSON.stringify(payload),
      })
    } catch {
      /* best-effort; the draft stays for retry */
    }
  },

  markPhaseDone: (memberId, phase) => {
    const prev = get().progress[memberId] || {}
    persist(set, get, {
      progress: { ...get().progress, [memberId]: { ...prev, [phase]: true } },
    })
  },

  addGoal: (memberId, fields) => {
    const goal = {
      id: newGoalId(),
      suggestionKey: null,
      amount: null,
      notSure: false,
      ...fields,
    }
    const list = get().goals[memberId] ?? []
    persist(set, get, { goals: { ...get().goals, [memberId]: [...list, goal] } })
    return goal.id
  },

  updateGoal: (memberId, goalId, fields) => {
    const list = (get().goals[memberId] ?? []).map((g) =>
      g.id === goalId ? { ...g, ...fields } : g,
    )
    persist(set, get, { goals: { ...get().goals, [memberId]: list } })
  },

  removeGoal: (memberId, goalId) => {
    const list = (get().goals[memberId] ?? []).filter((g) => g.id !== goalId)
    persist(set, get, { goals: { ...get().goals, [memberId]: list } })
  },

  // Shallow-merge a patch into one member's finances object.
  updateFinances: (memberId, patch) => {
    const current = get().finances[memberId] ?? {}
    persist(set, get, {
      finances: { ...get().finances, [memberId]: { ...current, ...patch } },
    })
  },

  // Shallow-merge a patch into one member's gut-check record.
  updateCheck: (memberId, patch) => {
    const current = get().checks[memberId] ?? {}
    persist(set, get, {
      checks: { ...get().checks, [memberId]: { ...current, ...patch } },
    })
  },
}))
