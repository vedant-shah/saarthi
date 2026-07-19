"""
Session-end summarizer — idempotent persistence of conversation outcomes.

`close_session` is the single convergence point for both close triggers (the
`/session/close` beacon and the 60s idle sweep / startup scan). It reads the
session JSONL transcript, asks the model to extract durable outcomes via a forced
`summarize` tool, and dispatches each to the matching writer with `writer=member`
(so cross-member isolation holds even if the model hallucinates another member).

Status lives in the transcript, not a marker file. The durable 'done' signal is a
terminal `post_processing` event appended LAST, only after EVERY entity persisted
successfully. If a write fails, no completion event is written, so the catch-up
scan retries; the entity writers are idempotent (dedup_id) so the retry never
duplicates what already landed. Malformed entries are dropped at validation —
they are not failures, so a structurally-bad entry can never wedge the session
into infinite retry.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import date

from backend.agent.context_registry import REGISTRY
from backend.agent.current_value import key_for_id
from backend.agent.llm_provider import LLMProvider, SystemBlock, get_provider
from backend.agent.promotion import _split_about, promote_observations
from backend.agent.roster import slugify
from backend.agent.transcripts import (
    is_post_processed,
    mark_post_processed,
    transcript_path,
)
from backend.agent.writers import (
    accrue_inference,
    accrue_risk_profile,
    append_conversation_summary,
    record_status_transition,
    stage_cross_member_observation,
    write_asset,
    write_family_inference,
    write_financial_fact,
    write_goal,
    write_life_event,
    write_recommendation,
)
from backend.config import settings
from backend.utils.markdown_io import read_markdown_or_none, strip_frontmatter

logger = logging.getLogger(__name__)

_DEFAULT_PRIORITY = 2

_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider:
    """Lazy module-level provider so close_session does not need one injected."""
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def reset_provider() -> None:
    """Drop the cached summarizer provider so the next run rebuilds it with the
    current API key. Called when the key changes at runtime (Settings panel): this
    module caches its own provider independently of the chat one, so without this
    a saved key would not reach the summarizer until a restart."""
    global _provider
    _provider = None


def _existing_memory_for(member: str) -> str:
    """The member's current-value files concatenated with their `<!-- id:... -->`
    markers intact, so the extractor sees what already exists instead of running
    blind (M3) — and, downstream, can target those ids with edit-ops (M4).

    Narrative files (the free-text notes the member wrote) are included too, as
    read-only background: without them the extractor can't see clarifications
    that only live in notes (e.g. "the 61k was an f&f, not the joining bonus")
    and re-derives them wrong. They carry no id markers, so they're never targeted.

    Resolved via `settings.memory_dir` — the SAME base the writers use — so the
    extractor reads exactly the tree where writes land. Frontmatter is stripped
    (it carries no facts); the id comments live in the body and survive, which is
    the whole point and is asserted by test."""
    base = settings.resolve(settings.memory_dir) / "members" / member
    sections: list[str] = []
    for entry in REGISTRY:
        if entry.scope != "member" or entry.mode not in ("current-value", "narrative"):
            continue
        fname = entry.path_template.rsplit("/", 1)[-1]
        content = read_markdown_or_none(base / fname)
        if not content:
            continue
        body = strip_frontmatter(content).strip()
        if body:
            sections.append(f"### {entry.name}\n{body}")
    return "\n\n".join(sections)


def _roster_context(memory_root) -> str | None:
    """The household roster, handed to the extractor so it can name a cross-member
    `about` by its real member_id (e.g. 'alpa') instead of a relationship word
    ('mum') pulled from the conversation. Returns None when there is no roster."""
    content = read_markdown_or_none(memory_root / "family" / "household.md")
    if not content:
        return None
    body = strip_frontmatter(content).strip()
    if not body:
        return None
    return (
        "HOUSEHOLD ROSTER — the family members already on record. When a "
        "cross_member_observation is about someone listed here, set its `about` to "
        "that person's member_id (the first column), never a relationship word.\n\n"
        + body
    )


def _resolve_target_key(member: str, fname: str, target_id: str, fallback_key: str) -> str:
    """Resolve an extractor `target_id` to the existing block's canonical key so
    an update lands in place instead of under a parallel key (closes #2/#6). A
    missing or unknown id falls back to the candidate's own key — i.e. appended
    as a new block (decision 2026-06-15: bad target_id -> append)."""
    if not target_id:
        return fallback_key
    base = settings.resolve(settings.memory_dir) / "members" / member
    content = read_markdown_or_none(base / fname) or ""
    return key_for_id(content, target_id) or fallback_key


_SUMMARIZER_SYSTEM = """You are the extraction stage of a two-stage memory pipeline for a personal financial advisor. Read one closed advisory conversation with a single family member and call the `summarize` tool once with the durable outcomes it established. A separate automatic stage files each item into the right place and decides how it is stored — your only job is to report, faithfully and with evidence, what this conversation actually established. You never decide storage and never supply precision the conversation did not give.

INSTRUCTIONS
1. Read the entire conversation before extracting.
2. Extract only what was established or stated in THIS session. Do not restate standing facts that did not change.
3. Give every factual or behavioral item a short basis — the words or exchange it rests on. If you cannot point to a basis, do not record the item.
4. If the member revises something during the session, report only the latest version; the correction wins.
5. When you are unsure what an item refers to, or a figure is too vague to be a fact, leave it out. Assert only what is clear.
6. Keep summary_3_lines to three short lines.
7. ALWAYS call the `summarize` tool exactly once. Even if nothing durable was established, still call it — with just summary_3_lines saying so and every other field empty. Never answer in plain text instead of calling the tool; a text-only reply is treated as a failure and the whole session is lost.
8. You may be shown the member's EXISTING MEMORY. When a financial fact or asset you report is a CHANGE to one already there, set its `target_id` to that block's id (from its `<!-- id:... -->` marker) so it updates in place instead of creating a duplicate. Match by MEANING, not exact label — "personal spending" and an existing "total expense" are the same fact, so target it. Omit `target_id` only for a genuinely new fact.

DO
- financial_fact_updates: RECURRING income, expense, liability, or investment contribution the member states — a monthly/annual salary, an ongoing recurring expense, a standing liability, or a regular contribution into ANY instrument (a SIP, recurring deposit, or standing buy into a fund, stock, or smallcase). Give category (income | expense | liability | investment), a short label in their own words, the amount per period, and cadence (monthly or annual). This file is the recurring cash-flow picture, NOT a list of one-off transactions.
- asset_updates: the current VALUE of something the member says they HOLD — cash/savings (e.g. an emergency fund), a fixed deposit, EPF/PPF, gold, property, or the balance of a fund, stock, or smallcase. Give the asset class, a short label in their own words, and the value as a single amount they state (a balance, never a per-month contribution).
- goal_updates: goals set, refined, completed, or cancelled — the action, plus target figure and horizon when stated.
- inferences: behavioral signals the conversation reveals — risk tolerance and horizon (kind "risk"), or loss aversion, decision style, liquidity comfort, financial anxiety (kind "behavior") — each with its basis and an honest confidence.
- cross_member_observations: anything the member says about ANOTHER person (e.g. "my dad is retiring next year") — the observation, who it is about, and the basis. When that observation bears on the family's MONEY picture, when it could change the advice another member gets (a relative retiring, a big shared liability, someone who depends on them, a joint goal), ALSO give a short `topic` (a few words like "retirement" or "home_loan"), a `relevance` phrase saying why it matters financially (no figures, just the relevance), and a `pointer` to where that person's actual number would live if you can name it (e.g. members/<id>/finances.md). Leave topic and relevance out when the remark has no money bearing (a hobby, a mood); a plain observation is fine on its own. For `about`, use the person's member_id from the HOUSEHOLD ROSTER you are given when they are already on it (e.g. "alpa", not "mum" or "mother"); only use a plain name when the person is not yet in the roster.
- life_events_stated: events the member states — occurred or anticipated — INCLUDING one-off purchases, planned trips, and one-time windfalls (a new gadget, a vacation, an expected bonus or leave encashment). These are the home for anything one-off; they never go into financial_fact_updates.
- new_recommendations, status_transitions: advice the advisor gave, and any explicit status change to a prior goal or recommendation.
- Use the member's own framing for labels, titles, and topics, and keep each basis to one short clause.

DON'T
- Don't INVENT or estimate a figure the member did not give. Record an income, balance, or asset value only when the member states it; if they say something changed but give no number, report that it changed and omit the figure. A precise figure the member DOES state should be captured (a later upload supersedes it) — capturing a stated value is not "inventing".
- Don't record a PREVIOUS or no-longer-true figure as a current fact. If the member contrasts an old value with a new one ("take-home is 1.4L now, up from 1.1"), report only the current one (1.4L); the old number is context, not a fact to store. A previous salary is never a current income.
- Keep a recurring investment CONTRIBUTION separate from a holding's VALUE. A regular contribution into any instrument (a monthly SIP, a recurring deposit, a standing buy into a fund, stock, or smallcase) is a financial_fact_update with category "investment" and a cadence — it is the money flowing in, never an asset and never an expense. The current balance those contributions have built (a fund corpus, an FD, a stock or smallcase value) is the asset_update. Never record a contribution as an asset with a per-month value. Expenses are rent, EMIs, bills, and family support.
- Don't put a ONE-OFF purchase, planned trip, or one-time windfall into financial_fact_updates or asset_updates — a single gadget, a vacation, an expected bonus or leave payout is not recurring cash flow and would sit in the finances file forever as if ongoing. Record it as a life_event instead.
- Don't flip a behavioral read on a single offhand remark. Record an inference only when the conversation genuinely reveals it, and set confidence honestly: low for a passing hint, med for a clear signal, and high ONLY for a pattern that is explicitly stated or repeated across the conversation — never high on just one or two datapoints.
- Don't write a fact about another person into this member's record — put it in cross_member_observations, never as this member's own fact.
- Don't pad. Omit a field rather than fill it with a guess.

EXAMPLES
Input: "I switched jobs last month — take-home is Rs 1.4L now, up from 1.1. And I want to start saving for a house, maybe Rs 60L in 7 years."
Call: financial_fact_updates=[{category:"income", label:"salary", value:"140000", cadence:"monthly", basis:"switched jobs, take-home now Rs 1.4L"}]; goal_updates=[{title:"House purchase", action:"set", target:"60L", horizon:"7y", basis:"wants ~Rs 60L for a house in 7y"}]; summary_3_lines=["Switched jobs; take-home up to Rs 1.4L/mo","New goal: Rs 60L house in 7 years","Has income headroom to allocate"].

Input: "When my portfolio dropped last week I couldn't sleep — almost sold everything. I hate seeing red. Oh, and my dad's retiring next year."
Call: inferences=[{topic:"loss_aversion", kind:"behavior", claim:"strong loss aversion - distressed by drawdowns, urge to sell", basis:"couldn't sleep after a dip, 'hate seeing red'", confidence:"med"}]; cross_member_observations=[{observation:"retiring next year", about:"dad", basis:"'my dad's retiring next year'"}]. No financial_fact_updates or asset_updates — no figure was stated, so none is authored.

Input: "I remembered I also have about 2 lakh sitting in an FD, and roughly 50g of gold at home."
Call: asset_updates=[{asset_class:"fd", label:"fixed deposit", value:"200000", basis:"~2L in an FD"}, {asset_class:"gold", label:"physical gold", value:"50g", basis:"~50g gold at home"}]; summary_3_lines=["Disclosed previously-unmentioned assets","~Rs 2L in a fixed deposit","~50g physical gold at home"].

Input: "I run a couple of SIPs - 4k a month into HDFC Small Cap and 5k into a Nifty index fund. Separately I've got about 30k in direct stocks."
Call: financial_fact_updates=[{category:"investment", label:"HDFC Small Cap SIP", value:"4000", cadence:"monthly", basis:"4k/month SIP"}, {category:"investment", label:"Nifty index SIP", value:"5000", cadence:"monthly", basis:"5k/month into a Nifty index fund"}]; asset_updates=[{asset_class:"equity", label:"direct stocks", value:"30000", basis:"~30k in direct stocks"}]; summary_3_lines=["Runs monthly SIPs into a small-cap and an index fund","Holds ~Rs 30k in direct stocks","Recurring equity contributions in place"]. The SIPs are recurring contributions (investment cash flow); the 30k stock balance is a held asset.

CONTEXT
This runs once, automatically, when a session closes. You are extracting for one member's record only. Downstream, a deterministic reconciler files each item by its destination's rule and tags it source=conversation with the confidence you set; a low-confidence conversational value never overwrites a verified document, and a repeated behavioral signal accrues as evidence rather than replacing the prior read. Your honesty about basis and confidence is what decides whether a value is trusted, accrued, or held for confirmation."""

_SUMMARIZE_TOOL = {
    "name": "summarize",
    "description": "Report the durable outcomes this conversation established.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary_3_lines": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to 3 short lines summarizing the session.",
            },
            "new_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "priority": {"type": "integer", "enum": [1, 2, 3]},
                        "assumptions": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            "goal_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["set", "refine", "complete", "cancel"],
                        },
                        "target": {"type": "string"},
                        "horizon": {"type": "string"},
                        "basis": {"type": "string"},
                    },
                    "required": ["title", "action"],
                },
            },
            "financial_fact_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["income", "expense", "liability", "investment"],
                        },
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "cadence": {
                            "type": "string",
                            "enum": ["monthly", "annual"],
                        },
                        "basis": {"type": "string"},
                        "target_id": {
                            "type": "string",
                            "description": "If this CHANGES a fact already in EXISTING MEMORY, the id from that block's <!-- id:... --> marker, so it updates in place. Omit for a genuinely new fact.",
                        },
                    },
                    "required": ["category", "label", "value"],
                },
            },
            "asset_updates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset_class": {
                            "type": "string",
                            "enum": [
                                "cash", "equity", "mutual_fund", "fd",
                                "epf_ppf", "gold", "property", "other",
                            ],
                        },
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "basis": {"type": "string"},
                        "target_id": {
                            "type": "string",
                            "description": "If this CHANGES an asset already in EXISTING MEMORY, the id from that block's <!-- id:... --> marker, so it updates in place. Omit for a genuinely new asset.",
                        },
                    },
                    "required": ["asset_class", "label", "value"],
                },
            },
            "inferences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "kind": {"type": "string", "enum": ["risk", "behavior"]},
                        "claim": {"type": "string"},
                        "basis": {"type": "string"},
                        "confidence": {
                            "type": "string",
                            "enum": ["low", "med", "high"],
                        },
                    },
                    "required": ["topic", "kind", "claim", "basis"],
                },
            },
            "cross_member_observations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "observation": {"type": "string"},
                        "about": {"type": "string"},
                        "basis": {"type": "string"},
                        "topic": {
                            "type": "string",
                            "description": "Set ONLY if this bears on the family's money picture: a few-word topic like 'retirement' or 'home_loan'.",
                        },
                        "relevance": {
                            "type": "string",
                            "description": "Why it matters to the family financially, in words, NO figures. Set together with topic, or leave both out.",
                        },
                        "pointer": {
                            "type": "string",
                            "description": "Optional: where that person's actual figure would live, e.g. members/<id>/finances.md, if you can name it.",
                        },
                    },
                    "required": ["observation", "about"],
                },
            },
            "life_events_stated": {
                "type": "array",
                "items": {"type": "string"},
            },
            "status_transitions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "from_status": {"type": "string"},
                        "to_status": {"type": "string"},
                    },
                    "required": ["item", "from_status", "to_status"],
                },
            },
        },
        "required": ["summary_3_lines"],
    },
}


# Per-session async locks preventing TOCTOU on the check-summarize-mark body.
# Lazily created; keyed by (member, session_id).
_session_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _lock_for(member: str, session_id: str) -> asyncio.Lock:
    # setdefault is atomic at the dict level, so concurrent callers for the same
    # session always get the same lock without a check-then-set race.
    return _session_locks.setdefault((member, session_id), asyncio.Lock())


def _dedup_id(session_id: str, *parts: str) -> str:
    """Stable, content-derived id for a single entity within a session.

    Keyed on session_id + the entity's semantic identity ONLY — never on the run
    time or run date, which vary across retries and would defeat dedup. Two
    retries of the same session's post-processing produce the same id for the
    same entity, so the idempotent writers skip the re-write."""
    raw = "|".join((session_id, *parts))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _run(label: str, fn) -> bool:
    """Run one writer dispatch. Returns True on success; on failure logs and
    returns False so the caller can withhold the completion stamp and retry.

    Only environmental write failures reach here — malformed entries are dropped
    at validation in `_dispatch` before a writer is ever called."""
    try:
        fn()
        return True
    except Exception:
        logger.exception("memory_updater: writer failed (%s)", label)
        return False


# Goal action → lifecycle state written into goals.md.
_GOAL_LIFECYCLE = {
    "set": "ACTIVE",
    "refine": "ACTIVE",
    "complete": "ACHIEVED",
    "cancel": "DROPPED",
}


def _conversation_date(content: str) -> str:
    """The calendar date the conversation happened on, from the first turn's
    timestamp. Relative-time phrases ('yesterday') are resolved against THIS, not
    the processing date, which can be days later when the catch-up scan runs."""
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = rec.get("ts") if isinstance(rec, dict) else None
        if ts:
            return str(ts)[:10]
    return date.today().isoformat()


def _date_instruction(conv_date: str) -> str:
    """Tell the summarizer the conversation's date and to absolutize all
    relative time, so 'yesterday' never lands in memory as a relative word."""
    return (
        f"This conversation took place on {conv_date}. Resolve EVERY relative time "
        f"reference to an absolute YYYY-MM-DD date in everything you output "
        f"(summary lines, life events, goals, all text). 'today' is {conv_date}; "
        f"'yesterday' is the day before; convert 'last week', 'next month', 'in a "
        f"couple of weeks', and the like the same way. Never leave a relative word "
        f"like 'yesterday', 'today', or 'last week' in your output."
    )


def _dispatch(member: str, session_id: str, raw: dict, today: str) -> bool:
    """Stage 2 — route stage-1 candidates to per-file writers, each loading only
    its own target file and applying its registered mode (append / current-value
    / dated-log) via the writers. All writes use writer=member so cross-member
    isolation holds regardless of model output.

    Returns True only if every attempted write succeeded. Entries missing
    required fields are skipped (logged, not counted as failures) so a bad entry
    cannot block completion forever.

    INVARIANT: every UpsertOutcome — INSERTED, SUPERSEDED, NOOP, ACCRUED, and
    STAGED — is a SUCCESSFUL dispatch. STAGED (a lower-authority conflict held
    for confirmation) is a clean outcome, not a failure, so it must never
    withhold the completion stamp. Only a raised exception (environmental write
    failure) makes _run return False and triggers retry."""
    all_ok = True

    summary_lines = raw.get("summary_3_lines") or []
    if summary_lines:
        all_ok &= _run(
            "conversation_summary",
            lambda: append_conversation_summary(
                member,
                date=today,
                summary_lines=summary_lines,
                dedup_id=_dedup_id(session_id, "summary"),
            ),
        )

    for rec in raw.get("new_recommendations", []):
        title = rec.get("title")
        if not title:
            logger.warning("memory_updater: skipping recommendation with no title")
            continue
        all_ok &= _run(
            "recommendation",
            lambda rec=rec, title=title: write_recommendation(
                member,
                title=title,
                priority=rec.get("priority", _DEFAULT_PRIORITY),
                body=rec.get("assumptions", ""),
                date=today,
                dedup_id=_dedup_id(session_id, "rec", title),
            ),
        )

    for fact in raw.get("financial_fact_updates", []):
        category = fact.get("category")
        label = fact.get("label")
        value = fact.get("value")
        if not (category and label and value):
            logger.warning("memory_updater: skipping incomplete financial_fact_update")
            continue
        key = _resolve_target_key(
            member, "finances.md", fact.get("target_id", ""), f"{category}.{label}"
        )
        all_ok &= _run(
            "financial_fact",
            lambda key=key, value=value, fact=fact, category=category: write_financial_fact(
                member,
                key=key,
                value=value,
                category=category,
                cadence=fact.get("cadence", "monthly"),
                source="conversation",
                confidence="low",
                as_of=today,
                dedup_id=_dedup_id(session_id, "fin", key, value),
            ),
        )

    for asset in raw.get("asset_updates", []):
        asset_class = asset.get("asset_class")
        label = asset.get("label")
        value = asset.get("value")
        if not (asset_class and label and value):
            logger.warning("memory_updater: skipping incomplete asset_update")
            continue
        key = _resolve_target_key(
            member, "portfolio_summary.md", asset.get("target_id", ""), f"{asset_class}.{label}"
        )
        all_ok &= _run(
            "asset",
            lambda key=key, value=value, asset_class=asset_class: write_asset(
                member,
                key=key,
                value=value,
                asset_class=asset_class,
                source="conversation",
                confidence="low",
                as_of=today,
                dedup_id=_dedup_id(session_id, "asset", key, value),
            ),
        )

    for goal in raw.get("goal_updates", []):
        title = goal.get("title")
        action = goal.get("action")
        if not (title and action in _GOAL_LIFECYCLE):
            logger.warning("memory_updater: skipping goal_update missing title/action")
            continue
        target = goal.get("target", "")
        # A set/refine with no target would write a blank goal — don't (§4:
        # target required or the goal is not written). Complete/cancel needs none.
        if action in ("set", "refine") and not target:
            logger.warning(
                "memory_updater: skipping %s goal '%s' with no target", action, title
            )
            continue
        lifecycle = _GOAL_LIFECYCLE[action]
        all_ok &= _run(
            "goal",
            lambda title=title, target=target, goal=goal, lifecycle=lifecycle: write_goal(
                member,
                title=title,
                target=target,
                horizon=goal.get("horizon", ""),
                lifecycle=lifecycle,
                source="conversation",
                confidence="low",
                as_of=today,
                dedup_id=_dedup_id(session_id, "goal", title, lifecycle),
            ),
        )
        # A completion/cancellation leaves a pointer in agent_notes (§4).
        if action in ("complete", "cancel"):
            all_ok &= _run(
                "goal_status_note",
                lambda title=title, lifecycle=lifecycle: record_status_transition(
                    member,
                    item=title,
                    from_status="ACTIVE",
                    to_status=lifecycle,
                    date=today,
                    dedup_id=_dedup_id(session_id, "goalnote", title, lifecycle),
                ),
            )

    for inf in raw.get("inferences", []):
        topic = inf.get("topic")
        kind = inf.get("kind")
        claim = inf.get("claim")
        basis = inf.get("basis")
        if not (topic and claim and basis and kind in ("risk", "behavior")):
            logger.warning(
                "memory_updater: skipping inference missing topic/kind/claim/basis"
            )
            continue
        confidence = inf.get("confidence", "low")
        if kind == "risk":
            all_ok &= _run(
                "risk_inference",
                lambda topic=topic, claim=claim, basis=basis, confidence=confidence: accrue_risk_profile(
                    member,
                    dimension=topic,
                    stance=claim,
                    basis=basis,
                    confidence=confidence,
                    as_of=today,
                    dedup_id=_dedup_id(session_id, "risk", topic, claim),
                ),
            )
        else:
            all_ok &= _run(
                "behavior_inference",
                lambda topic=topic, claim=claim, basis=basis, confidence=confidence: accrue_inference(
                    member,
                    topic=topic,
                    claim=claim,
                    basis=basis,
                    confidence=confidence,
                    as_of=today,
                    dedup_id=_dedup_id(session_id, "inf", topic, claim),
                ),
            )

    for obs in raw.get("cross_member_observations", []):
        observation = obs.get("observation")
        about = obs.get("about")
        if not (observation and about):
            logger.warning("memory_updater: skipping incomplete cross_member_observation")
            continue
        all_ok &= _run(
            "cross_member_observation",
            lambda observation=observation, about=about: stage_cross_member_observation(
                member,
                observation=observation,
                about=about,
                date=today,
                dedup_id=_dedup_id(session_id, "xmem", about, observation),
            ),
        )
        # When the observation bears on the family's money picture, also file a
        # values-free entry in the cross-member relevance index, keyed by the
        # same member-id slug the roster uses so the pointer/lazy-pull line up.
        topic = obs.get("topic")
        relevance = obs.get("relevance")
        if topic and relevance:
            about_id = slugify(_split_about(about)[0])
            all_ok &= _run(
                "family_inference",
                lambda about_id=about_id, topic=topic, relevance=relevance, obs=obs: write_family_inference(
                    member,
                    about=about_id,
                    topic=topic,
                    relevance=relevance,
                    pointer=obs.get("pointer", ""),
                    source="inference",
                    confidence="low",
                    as_of=today,
                    dedup_id=_dedup_id(session_id, "famidx", about_id, topic),
                ),
            )

    for event in raw.get("life_events_stated", []):
        if not isinstance(event, str) or not event.strip():
            logger.warning("memory_updater: skipping empty life event")
            continue
        all_ok &= _run(
            "life_event",
            lambda event=event: write_life_event(
                member,
                description=event,
                date=today,
                dedup_id=_dedup_id(session_id, "life_event", event),
            ),
        )

    for transition in raw.get("status_transitions", []):
        item = transition.get("item")
        from_status = transition.get("from_status")
        to_status = transition.get("to_status")
        if not (item and from_status and to_status):
            logger.warning("memory_updater: skipping incomplete status transition")
            continue
        all_ok &= _run(
            "status_transition",
            lambda item=item, from_status=from_status, to_status=to_status: record_status_transition(
                member,
                item=item,
                from_status=from_status,
                to_status=to_status,
                date=today,
                dedup_id=_dedup_id(session_id, "status", item, from_status, to_status),
            ),
        )

    return all_ok


async def close_session(member: str, session_id: str) -> None:
    """Summarize and persist a closed session. Idempotent via the transcript's
    terminal post-processing event.

    No-op if already post-processed or if there is no transcript (nothing to
    summarize, and nothing the catch-up scan could find). On a partial write
    failure no completion event is written, so the scan retries; the idempotent
    writers absorb the re-run.

    The per-session async lock closes the TOCTOU window: two concurrent callers
    (startup scan + idle sweep + beacon) both pass the initial status check
    before either writes, but only one proceeds through the summarizer. The
    completion event is written LAST so a crash mid-summarize leaves the session
    retryable."""
    async with _lock_for(member, session_id):
        if is_post_processed(member, session_id):
            logger.info("memory_updater: already post-processed %s/%s", member, session_id)
            return

        content = read_markdown_or_none(transcript_path(member, session_id))
        if content is None:
            logger.info(
                "memory_updater: no transcript %s/%s — nothing to process", member, session_id
            )
            return

        conv_date = _conversation_date(content)
        system_blocks = [
            SystemBlock(text=_SUMMARIZER_SYSTEM),
            SystemBlock(text=_date_instruction(conv_date)),
        ]
        existing = _existing_memory_for(member)
        if existing:
            system_blocks.append(
                SystemBlock(
                    text=(
                        f"EXISTING MEMORY for {member} — the facts already stored. "
                        "Do not restate anything here that did not change this "
                        "session; report only what this conversation adds or "
                        "changes. Each block's `<!-- id:... -->` marker is its "
                        f"stable handle.\n\n{existing}"
                    )
                )
            )

        roster = _roster_context(settings.resolve(settings.memory_dir))
        if roster:
            system_blocks.append(SystemBlock(text=roster))

        raw = await _get_provider().complete_json(
            system=system_blocks,
            messages=[{"role": "user", "content": content}],
            tool=_SUMMARIZE_TOOL,
            model=settings.summarizer_model,
            max_tokens=8000,
            thinking_budget=settings.summarizer_thinking_budget,
            label="summarizer",
        )

        # None signals the summarizer call FAILED (vs {} for a clean empty
        # extraction). A failure must not be stamped complete, or the session's
        # memory is silently lost; leaving it un-stamped lets the catch-up scan
        # retry it.
        if raw is None:
            logger.warning(
                "memory_updater: summarizer call failed %s/%s — leaving un-stamped for retry",
                member,
                session_id,
            )
            return

        # Write facts dated to when the conversation happened (and what the
        # summarizer was told 'today' is), not the later processing date.
        today = conv_date
        all_ok = _dispatch(member, session_id, raw, today)

        # After staging this session's cross-member observations, promote any
        # newly-mentioned family members into the household roster (#7). Idempotent
        # and family-scoped; a failure withholds the stamp so the scan retries.
        all_ok &= _run(
            "promote_observations",
            lambda: promote_observations(
                settings.resolve(settings.memory_dir), today=today
            ),
        )

        if all_ok:
            mark_post_processed(member, session_id)
            logger.info("memory_updater: post-processed %s/%s", member, session_id)
        else:
            logger.warning(
                "memory_updater: post-processing incomplete %s/%s — will retry",
                member,
                session_id,
            )
