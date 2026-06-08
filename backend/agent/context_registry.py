from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PreloadPolicy = Literal["always", "classifier_predicted", "agent_invoked"]

# File update mode (MEMORY_DATA_MODEL §2). A property of the FILE, so the stage-2
# reconciler knows how to treat a candidate from its target file alone.
#   append        — happened and stays true (insert, dedup)
#   current-value — latest value that changes (supersede-on-match)
#   dated-log     — time series of full snapshots (never superseded)
#   narrative     — free prose the pipeline never parses
#   reference     — a skill/playbook, not a memory file (no update mode)
Mode = Literal["append", "current-value", "dated-log", "narrative", "reference"]


@dataclass(frozen=True)
class ContextEntry:
    name: str
    path_template: str
    description: str
    mode: Mode
    preload: PreloadPolicy
    scope: Literal["family", "member", "skill", "working"]
    required: bool = False


REGISTRY: tuple[ContextEntry, ...] = (
    # --- always ---
    ContextEntry(
        name="family.household",
        path_template="memory/family/household.md",
        description="Roster + family tree, shared tax status, joint assets/liabilities",
        mode="current-value",
        preload="always",
        scope="family",
        required=True,
    ),
    ContextEntry(
        name="member.profile",
        path_template="memory/members/{member}/profile.md",
        description="Identity: age, role, relationships, earning status, financial literacy — no money figures",
        mode="current-value",
        preload="always",
        scope="member",
        required=True,
    ),
    ContextEntry(
        name="member.conversations",
        path_template="memory/members/{member}/conversations.md",
        description="Last 3-5 dated session summaries",
        mode="append",
        preload="always",
        scope="member",
    ),
    ContextEntry(
        name="family.calendar",
        path_template="memory/family/calendar.md",
        description="Recurring events and future state changes",
        mode="append",
        preload="always",
        scope="family",
    ),
    ContextEntry(
        name="skill.core_system",
        path_template="skills/core_system.md",
        description="Standing advisor instructions",
        mode="reference",
        preload="always",
        scope="skill",
        required=True,
    ),
    # --- classifier_predicted ---
    ContextEntry(
        name="member.portfolio_summary",
        path_template="memory/members/{member}/portfolio_summary.md",
        description="Current investment holdings and allocation",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    ContextEntry(
        name="member.goals",
        path_template="memory/members/{member}/goals.md",
        description="Goal planning, surplus allocation",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    ContextEntry(
        name="member.finances",
        path_template="memory/members/{member}/finances.md",
        description="Cash flow + debt: income, recurring expenses, liabilities",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    ContextEntry(
        name="member.risk_profile",
        path_template="memory/members/{member}/risk_profile.md",
        description="Revealed risk tolerance + investment horizon",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    # tax + insurance: DEFERRED files (MEMORY_DATA_MODEL §13 — not built yet). Kept
    # registered so the frozen `tax_planning`/`insurance` intents still resolve to a
    # name; the assembler skips them gracefully until the files exist.
    ContextEntry(
        name="member.tax",
        path_template="memory/members/{member}/tax.md",
        description="80C/80D, ELSS, capital gains questions (deferred — file not built yet)",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    ContextEntry(
        name="member.insurance",
        path_template="memory/members/{member}/insurance.md",
        description="Coverage assessment (deferred — file not built yet)",
        mode="current-value",
        preload="classifier_predicted",
        scope="member",
    ),
    ContextEntry(
        name="family.inferences",
        path_template="memory/family/inferences.md",
        description="Cross-member financial observations (high confidence)",
        mode="current-value",
        preload="classifier_predicted",
        scope="family",
    ),
    # --- agent_invoked: playbooks ---
    ContextEntry(
        name="skill.surplus_allocation",
        path_template="skills/surplus_allocation.md",
        description="Deploying spare cash (FD vs MF, lump sum vs SIP decisions)",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    ContextEntry(
        name="skill.emergency_response",
        path_template="skills/emergency_response.md",
        description="Sudden expense or financial shock",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    ContextEntry(
        name="skill.goal_planning",
        path_template="skills/goal_planning.md",
        description="Setting or modifying a financial goal",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    ContextEntry(
        name="skill.savings_strategy",
        path_template="skills/savings_strategy.md",
        description="Monthly cash flow, SIP setup, budget review",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    ContextEntry(
        name="skill.financial_literacy",
        path_template="skills/financial_literacy.md",
        description="Definitions, concepts, financial education",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    ContextEntry(
        name="skill.personal_finance",
        path_template="skills/personal_finance.md",
        description="Holistic review, multi-topic planning",
        mode="reference",
        preload="agent_invoked",
        scope="skill",
    ),
    # --- agent_invoked: on-demand memory ---
    ContextEntry(
        name="member.portfolio_snapshots",
        path_template="memory/members/{member}/portfolio_snapshots.md",
        description="Full dated holdings history (every upload/review)",
        mode="dated-log",
        preload="agent_invoked",
        scope="member",
    ),
    ContextEntry(
        name="member.recommendations",
        path_template="memory/members/{member}/recommendations.md",
        description="Advice given and its status (loadable on demand — previously written but never read back)",
        mode="append",
        preload="agent_invoked",
        scope="member",
    ),
    ContextEntry(
        name="member.life_events",
        path_template="memory/members/{member}/life_events.md",
        description="Stated life events, occurred or anticipated",
        mode="append",
        preload="agent_invoked",
        scope="member",
    ),
    ContextEntry(
        name="member.inferences",
        path_template="memory/members/{member}/inferences.md",
        description="Behavioral inferences (loss aversion, decision style) — low confidence",
        mode="current-value",
        preload="agent_invoked",
        scope="member",
    ),
    ContextEntry(
        name="member.agent_notes",
        path_template="memory/members/{member}/agent_notes.md",
        description="Prior agent reasoning, status transitions, superseded pointers",
        mode="append",
        preload="agent_invoked",
        scope="member",
    ),
    ContextEntry(
        name="member.narrative",
        path_template="memory/members/{member}/narrative.md",
        description="Free-prose human notes (never parsed)",
        mode="narrative",
        preload="agent_invoked",
        scope="member",
    ),
    # --- agent_invoked: staging queues (working/) ---
    ContextEntry(
        name="working.cross_member_observations",
        path_template="memory/working/cross_member_observations.md",
        description="Observations one member made about another, pending confirmation",
        mode="append",
        preload="agent_invoked",
        scope="working",
    ),
    ContextEntry(
        name="working.discrepancies",
        path_template="memory/working/discrepancies.md",
        description="Lower-authority values conflicting with a stored higher-authority one, pending confirmation",
        mode="append",
        preload="agent_invoked",
        scope="working",
    ),
)

_BY_NAME: dict[str, ContextEntry] = {e.name: e for e in REGISTRY}


def entries_by_policy(policy: PreloadPolicy) -> list[ContextEntry]:
    return [e for e in REGISTRY if e.preload == policy]


def entry_by_name(name: str) -> ContextEntry | None:
    return _BY_NAME.get(name)


def resolve_path(entry: ContextEntry, member: str, project_root: Path) -> Path:
    path = entry.path_template.replace("{member}", member)
    return project_root / path
