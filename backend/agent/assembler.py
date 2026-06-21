from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypedDict

from backend.agent.aggregator import read_family_name
from backend.agent.context_registry import entries_by_policy, resolve_path
from backend.agent.current_value import strip_superseded
from backend.agent.llm_provider import SystemBlock
from backend.agent.staleness import annotate_stale_blocks
from backend.config import settings
from backend.utils.markdown_io import read_markdown_or_none, strip_frontmatter

logger = logging.getLogger(__name__)


class ClassifierOutput(TypedDict):
    context_level: Literal["MINIMAL", "FULL"]
    relevant_memory_files: list[str]
    is_followup: bool


@dataclass(frozen=True)
class AssembledPrompt:
    system: list[SystemBlock]
    messages: list[dict]
    context_level: Literal["MINIMAL", "FULL"]
    debug: dict


class AssemblyError(Exception):
    pass


# Human-readable section headers for each always-loaded registry entry
_SECTION_HEADERS: dict[str, str] = {
    "skill.core_system": "Standing instructions",
    "family.household": "Household",
    "member.profile": "Member profile",
    "member.conversations": "Recent conversations",
    "member.notes": "Notes from the member",
    "family.calendar": "Family calendar",
    "member.finances": "Finances (income, expenses, debt)",
    "member.portfolio_summary": "Investments",
    "member.goals": "Goals",
    "member.risk_profile": "Risk profile",
}


def _build_catalog() -> str:
    lines: list[str] = []

    skill_entries = [e for e in entries_by_policy("agent_invoked") if e.scope == "skill"]
    lines.append("AVAILABLE PLAYBOOKS — call read_context(name) when handling these question types:")
    for entry in skill_entries:
        lines.append(f"- {entry.name}: {entry.description}")

    memory_entries = entries_by_policy("classifier_predicted") + [
        e for e in entries_by_policy("agent_invoked") if e.scope != "skill"
    ]
    lines.append("")
    lines.append("AVAILABLE MEMORY — call read_context(name) when you need this data on-demand:")
    for entry in memory_entries:
        lines.append(f"- {entry.name}: {entry.description}")

    lines.append("")
    lines.append(
        "OLDER CHATS — call recall_conversation(query) to keyword-search past "
        "conversations further back than the recent summaries above."
    )

    return "\n".join(lines)


def _tail_summary_blocks(body: str, count: int) -> str:
    """Keep only the last `count` dated '## ' blocks of a conversations file.

    Session summaries accumulate one block per session forever; preloading all of
    them would bloat Tier 1 at scale. This truncation is read-side only — the
    full file stays on disk and older summaries remain reachable on demand via
    recall_conversation."""
    if count <= 0:
        return body
    lines = body.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
    if len(starts) <= count:
        return body
    return "\n".join(lines[starts[-count]:]).strip()


def _build_full_prompt(
    *,
    active_member: str,
    classifier_output: ClassifierOutput,
    in_session_history: list[dict],
    user_message: str,
    memory_root,
    skills_root,
) -> AssembledPrompt:
    project_root = settings.project_root
    loaded: list[str] = []
    loaded_paths: set = set()
    missing: list[str] = []
    tier1_parts: list[str] = []

    # Session context (top of Tier 1)
    today = date.today().isoformat()
    family_name = read_family_name(memory_root)
    context_lines = [f"- Today's date: {today}", f"- Speaking with: {active_member}"]
    if family_name:
        context_lines.insert(1, f"- Family: {family_name}")
    tier1_parts.append("# Session context\n" + "\n".join(context_lines))

    # Always-loaded entries from registry, in declaration order
    for entry in entries_by_policy("always"):
        path = resolve_path(entry, active_member, project_root)
        content = read_markdown_or_none(path)

        if content is None:
            if entry.required:
                raise AssemblyError(
                    f"required context missing: {entry.name} at {path}"
                )
            logger.warning("assembler: optional entry missing: %s at %s", entry.name, path)
            missing.append(entry.name)
            continue

        body = strip_frontmatter(content)
        # Tier 1 stays bounded as history grows: preload only the most recent
        # session summaries; older ones are reachable via recall_conversation.
        if entry.name == "member.conversations":
            body = _tail_summary_blocks(body, settings.preloaded_summary_count)
        # Show only live values: drop SUPERSEDED history (kept on disk) and flag
        # long-stale CURRENT figures as possibly outdated. Both are read-side
        # only; stored memory is untouched.
        if entry.mode == "current-value":
            body = strip_superseded(body)
            body = annotate_stale_blocks(body, today=today)
        header = _SECTION_HEADERS.get(entry.name, entry.name)
        if entry.scope == "member":
            header = f"{header} — {active_member}"
        tier1_parts.append(f"# {header}\n{body.strip()}")
        loaded.append(entry.name)
        loaded_paths.add(path)

    tier1_text = "\n\n".join(tier1_parts)
    tier1 = SystemBlock(text=tier1_text, cache=False)

    # Tier 2 — classifier-predicted files (Day 1: always empty; coded for forward compat)
    relevant_files = classifier_output.get("relevant_memory_files", [])
    system_blocks: list[SystemBlock] = [tier1]

    if relevant_files:
        tier2_parts: list[str] = []
        for name in relevant_files:
            path = project_root / "memory" / f"{name}.md"
            if path in loaded_paths:
                continue  # already in Tier 1 (now-always file); don't double-load
            content = read_markdown_or_none(path)
            if content is None:
                logger.warning("assembler: tier2 file missing: %s", name)
                missing.append(name)
                continue
            body = strip_frontmatter(content)
            tier2_parts.append(f"# {name}\n{body.strip()}")
            loaded.append(name)
        if tier2_parts:
            tier2_text = "\n\n".join(tier2_parts)
            system_blocks.append(SystemBlock(text=tier2_text, cache=False))

    catalog = SystemBlock(text=_build_catalog(), cache=False)
    system_blocks.append(catalog)

    messages = in_session_history + [{"role": "user", "content": user_message}]

    return AssembledPrompt(
        system=system_blocks,
        messages=messages,
        context_level="FULL",
        debug={
            "loaded": loaded,
            "missing": missing,
            "tier1_chars": len(tier1_text),
        },
    )


def assemble(
    *,
    active_member: str,
    classifier_output: ClassifierOutput,
    in_session_history: list[dict],
    user_message: str,
    memory_root,
    skills_root,
) -> AssembledPrompt:
    # Memory loads on EVERY turn, regardless of the classifier's context_level.
    # MINIMAL is no longer allowed to starve the prompt: a greeting the classifier
    # misjudges must never leave the agent blind to what it has on file (it would
    # then confidently deny knowing the member). The classifier still selects
    # intent -> Tier 2 files inside _build_full_prompt.
    return _build_full_prompt(
        active_member=active_member,
        classifier_output=classifier_output,
        in_session_history=in_session_history,
        user_message=user_message,
        memory_root=memory_root,
        skills_root=skills_root,
    )
