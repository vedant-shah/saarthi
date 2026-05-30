# Family Financial Advisor

> A private AI advisor that learns your whole family's money, teaches you how to think about it, and grows with you over time.

Most money tools are built for one person and one account. Real family decisions aren't like that. When you ask *"should I prepay the home loan or invest the surplus?"*, the honest answer depends on your parents' retirement runway, your sibling's education timeline, and your spouse's job stability, not just your own balance sheet.

This is an AI advisor that knows every family member as a distinct person, explains its reasoning so you understand each decision yourself, and is built to make you more financially literate, not to sell you a product.

And it isn't a search box you query once and forget. You talk to it like a family friend who happens to be a great advisor, and every conversation makes it understand your family a little better. The advice compounds, the way counsel from someone who has known you for a decade beats counsel from someone you just met.

It runs on your own machine. Your financial data never leaves it.

---

## What actually makes it different

You can ask ChatGPT or Claude a money question today and get a fluent answer. Modern chatbots even remember a few things and can run a calculator. So we won't pretend they're useless. Here is what this product genuinely does that they don't:

| | A general chatbot | Family Financial Advisor |
|---|---|---|
| **Who it models** | One user, loosely remembered. | Every family member as a structured profile (income, age, risk appetite, goals) plus the household as a whole. You never re-explain everyone. |
| **The math it does** | A generic calculator tool for arithmetic. | Purpose-built financial models: Monte Carlo retirement simulations, goal-probability analysis, age-based allocation glide paths. |
| **How it learns your risk** | Asks you, and takes "aggressive" at face value. | Reads how you actually react to situations, because what people say and what they can stomach are different things. |
| **Its goal** | Answer the question, sometimes by naming a fund or stock. | Teach you the tradeoff so you can decide, and recommend categories ("a short-term debt fund"), never specific products. |
| **Where it lives** | A company's servers; your data may train future models. | Plain markdown files on your disk. Read, edit, back up, or delete everything it knows. |

---

## See it in action

### The maturing FD

> **You:** "Mom's ₹5L fixed deposit matures next month. Where should she park it?"

A generic chatbot gives a generic answer about debt funds. This advisor already knows Mom is 58, retiring in four years, that the family emergency fund is thin, and that she's uneasy with volatility. So instead of a product tip, it walks you through the decision:

> "Mom is four years from retirement, so this money has a short horizon and shouldn't take equity risk. Her emergency fund covers about two months of expenses, below the six you'd want at her age. **Top up the buffer first, then ladder the rest in a short-term debt fund.** An FD at ~7% barely beats inflation after tax, while a debt fund of similar safety has historically returned a little more and is more tax-efficient past three years."

You don't just get an answer. You learn *why short horizon means low risk* and *why the emergency fund comes first*. Next time, you'll reason it out yourself.

### Prepay the loan or invest?

> **You:** "I have ₹2L spare. Should I prepay my home loan or top up my SIP?"

It pulls your loan rate, your SIP, *and* the fact that your parents have no pension and you're their primary support:

> "On paper, your loan is at 8.4% and your SIP has averaged more, so investing wins. But you're the backstop for your parents on a single income. **Prepaying is a guaranteed 8.4%; the market's higher number is not guaranteed.** Given how much rides on you, I'd split it: prepay half to cut your fixed obligations, invest half to keep growth going."

It teaches the concept (guaranteed vs expected return) and grounds it in *your* family's risk, not a textbook.

### A first salary

> **Your daughter:** "I just got my first job. Everyone says start an SIP. What even is that?"

Here it's a patient teacher, not an advisor talking over a beginner's head:

> "An SIP just means investing a fixed amount every month, automatically, instead of one lump sum. It forces consistency and smooths out market ups and downs. But two things come first: a small emergency fund, and clearing any high-interest debt. Want to work out how much you could comfortably set aside each month?"

One advisor, shared by the whole family, meeting each person at their level.

---

## More than a question box

This is meant to be a relationship, not a transaction. Most tools, and most chatbots, wipe the slate after every answer. This one grows with your family.

- **It remembers the arc, not just the message.** It knows you prepaid part of your loan in March, that your daughter started her first SIP, that Mom's FD is maturing again. Each conversation builds on the last.
- **It checks in on its own.** Every quarter (or twice a year, your call) it runs a review: are the goals on track, did the SIPs actually happen, has anything drifted from the plan? Then it tells the family what needs attention, instead of waiting to be asked.
- **It gets better the more you use it.** Six months in, it understands your family's real tradeoffs better than any one-off question could.

---

## Built for how families actually talk

It's conversation-first by design. No dashboard to learn, no forms to fill, you just talk. And because the goal is to reach *every* member of a family, including the ones who would never open a finance app, it's built to live where families already are: **WhatsApp.** A parent who finds apps intimidating can simply send a message and get a thoughtful, personal answer back.

---

## Risk you'll actually stick to

Ask someone their risk appetite and almost everyone says "aggressive". Then the market drops 5% in a single day, they panic, and sell at the bottom. Self-reported risk tolerance is one of the least reliable numbers in personal finance.

So this advisor doesn't just ask. It gauges your real appetite **situationally**, from how you react to scenarios and to actual market moves, and builds a truer picture of what you can genuinely live with. The plan it gives you is one you'll still be comfortable with when markets get rough, not just on the day you answered a questionnaire.

---

## We teach, we don't sell

This is the core philosophy, and it shapes every other decision in the product.

Most finance apps make money when you buy something, so they're built to recommend products. This one has a different goal: **leave you understanding your own money well enough to decide for yourself.**

- **It explains the "why" behind every suggestion.** Not "buy this", but "here's the tradeoff, here's how to think about it, here's what I'd lean toward and the assumption it rests on."
- **It recommends categories, never specific products.** "A large-cap index fund", not "the XYZ Bluechip Fund". You learn what kind of instrument fits, then choose the specific one yourself or with a registered advisor.
- **It teaches concepts as they come up.** What an emergency fund is for, why horizon drives risk, how compounding actually works. The conversation doubles as a financial education.
- **It says "I don't know" honestly.** On HUF/NRI taxation, estate planning, and market timing, it defers to a CA, RIA, or lawyer instead of bluffing.

By staying at the level of categories and frameworks, the product also sits outside SEBI's definition of "investment advice". But that's a consequence of the philosophy, not the reason for it.

---

## How it works under the hood

### The family is the unit, not the individual

Every Indian finance app (Zerodha, Groww, INDmoney, Kuvera) gives *you* a dashboard. This treats your family as one financial entity with multiple members, so it can answer *"can Mom afford to retire in three years?"* by looking at her portfolio, the household emergency fund, your contribution capacity, and Dad's pension, all at once.

### Memory you can read with your own eyes

Everything the advisor knows lives in plain markdown files on your disk. No database, no cloud, no vector store. Open them in any text editor, see exactly what it believes about your family, and fix anything that's wrong. It loads that memory in tiers, the way a person recalls things: facts it always keeps in mind, details it pulls up when relevant, and things it looks up mid-thought. Fast replies, without stuffing every fact into every prompt.

### Purpose-built financial modeling

Generic chatbots can call a calculator now, so basic arithmetic isn't the edge. The edge is the *kind* of math: real financial modeling. Monte Carlo simulations that test whether a retirement corpus survives thousands of market paths, goal-probability analysis, allocation glide paths by age and horizon. The model reasons about your situation; proven algorithms produce numbers you can plan around.

### Privacy enforced in code, not by request

When Mom uses the app, her conversation stays hers. The family head sees a *summary*, not her transcript. If her session ever tries to write into Dad's private memory, the writer layer rejects it at the code level, not as a polite instruction to the AI. The prompt sent to Anthropic is also stripped of names, PAN, account numbers, and bank names before it leaves your machine.

### Memory updates itself from conversation

After a session ends, a small background process reads the transcript and quietly updates memory: new goals you mentioned in passing, life events, status changes on old recommendations. You never fill out a form. You just talk.

---

## Status

**Pre-MVP, in active development.** Being built in five working days.

| Day | What ships | Status |
|---|---|---|
| 1 | Backend streaming pipeline, memory loading, first real Claude reply | Done |
| 2 | React chat UI, per-member switching, transcript persistence | Done |
| 3 | Intent classifier, intent-gated memory, session summariser, writer privacy layer | In progress |
| 4 | Math tool-use loop, response guardrails, family dashboard | Planned |
| 5 | Onboarding wizard, conversation recall, real-family dogfooding | Planned |

See `MVP_BUILD_PLAN.md` for the full day-by-day plan and `agentic_workflow.md` for the technical architecture.

---

## Architecture at a glance

```
You type a message
        |
[Classifier - Haiku 4.5]      ~300ms   decides what memory to load
        |
[Assembler - pure Python]      ~50ms   builds the prompt from markdown files
        |
[Anonymiser]                    ~1ms   strips PAN, account numbers, names
        |
[Main agent - Sonnet 4.6]      3-8s    streams the reply, calls modeling tools
        |
[Guardrails]                            strips product names, hedges certainty
        |
You see the reply (streaming, token by token)
        |
[Session ends -> Summariser]   ~2s     updates memory files atomically
```

No vector database. No RAG. No knowledge graph. No SQLite. Just markdown files, a fast classifier, and a careful agent.

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+ |
| Backend | FastAPI + uvicorn (SSE streaming) |
| Main model | Claude Sonnet 4.6 |
| Classifier + summariser | Claude Haiku 4.5 |
| Storage | Plain markdown + JSONL files |
| Frontend | React + Vite + Tailwind v4 + Zustand |
| Scheduler | APScheduler |
| Channels | Web chat now, WhatsApp planned |
| Brokerage data (planned) | Kite MCP (Zerodha) |

What's deliberately *not* in the stack: no database (markdown scans are fast at single-family scale), no vector store (the whole corpus is under 30K tokens), no LangChain (the direct SDK is cleaner), no Redis (single machine).

---

## Privacy & regulatory positioning

- **Local-first:** all financial data, memory, and chat history stay on your machine.
- **Anonymised before any LLM call:** names become "Member A/B/C"; account numbers, PAN, Aadhaar, and phone numbers are stripped; bank and broker names are replaced with generic terms.
- **Category-only recommendations:** the advisor suggests *"a large-cap index fund"*, never a named product. This keeps it outside SEBI's definition of "investment advice".
- **Honest "I don't know":** on HUF/NRI taxation, estate planning, specific product comparisons, and market timing, it defers to a qualified professional.
- **No marketing data, no analytics, no telemetry.**

---

## Roadmap (post-MVP)

- **Phase 2, data & channels:** WhatsApp interface, multi-brokerage support (Groww), CAS statement upload, Account Aggregator integration.
- **Phase 3, deeper intelligence:** more skill playbooks (retirement, education funding, tax optimisation), advanced calculators (Monte Carlo, retirement corpus), conflicting-goal detection, a memory-editing UI.
- **Phase 4, scale:** optional cloud deployment, proper auth, mobile app, quarterly PDF reports.
- **Phase 5, platform:** the underlying architecture (family context + multi-persona memory + skill-driven agent) could generalise to other life domains, but only if it proves itself in finance first.

---

## Installation

> Setup instructions land here once the MVP stabilises (Day 5). For now the project is in active development; see `MVP_BUILD_PLAN.md` to follow along.

---

## Project documents

- `Family_Financial_Advisor_PRD.md`: the full product requirements doc, including memory schemas, the agent pipeline, and the design-decisions log.
- `PRD_Summary.md`: a shorter technical summary for stakeholders.
- `agentic_workflow.md`: the per-turn flow, prompt-caching strategy, and design principles.
- `MVP_BUILD_PLAN.md`: the five-day build plan.
- `.claude/day1_milestones.md`, `day2_milestones.md`, `day3_milestones.md`: milestone-level breakdowns of each day's work.

---

## License & status

Pre-release. Not yet open-sourced. Not affiliated with SEBI, IRDAI, or any registered investment advisor. This is an educational and decision-support tool, not investment advice. For complex tax, estate, or NRI situations, consult a SEBI-registered investment advisor or a qualified chartered accountant.
