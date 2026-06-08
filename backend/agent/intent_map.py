"""
Intent → Tier 2 memory file mapping (pure, no I/O).

Maps the 11 canonical PRD §6 intents to `classifier_predicted` registry entry
names, then resolves those to the path stems the assembler consumes
(`assembler.py` builds `project_root / "memory" / f"{stem}.md"`).

The keys of INTENT_FILES ARE the classifier's intent enum — classifier.py
reuses `INTENT_FILES.keys()`. Do not rename, add, or drop intents.
"""
from __future__ import annotations

from backend.agent.context_registry import entry_by_name

# CANONICAL 11 intents — VERBATIM from PRD §6 (frozen classifier vocabulary).
# Each tuple is the PRD's `files:` list for that intent, mapped to the registry
# entry names that actually exist and are preload="classifier_predicted".
# Three faithful reductions, noted inline:
#   - `recommendations` — no `member.recommendations` registry entry exists
#     (it is written by writers.py, never loaded as Tier 2). OMITTED.
#   - `calendar` — `family.calendar` is preload="always" (Tier 1), already
#     loaded; do not duplicate into Tier 2. OMITTED.
#   - all members' profiles (family_planning) — assembler loads only the ACTIVE
#     member's profile; multi-member profile loading is not supported yet.
#     Mapped to the family-relevant files that DO exist. NOTED as a gap.
INTENT_FILES: dict[str, tuple[str, ...]] = {
    "surplus_allocation": ("member.goals", "member.portfolio_summary", "member.finances"),  # +recommendations (omitted)
    "goal_feasibility": ("member.goals", "member.portfolio_summary"),
    "portfolio_review": ("member.portfolio_summary", "member.goals"),  # +recommendations (omitted)
    "financial_literacy": ("member.portfolio_summary",),
    "family_planning": ("member.finances", "member.goals"),  # +all members' profiles (gap)
    "insurance": ("member.insurance",),  # +calendar (Tier 1)
    "tax_planning": ("member.tax", "member.portfolio_summary"),  # +calendar (Tier 1)
    "debt_management": ("member.finances", "member.portfolio_summary"),
    "review_checkin": ("member.goals", "member.portfolio_summary", "member.finances", "member.insurance"),  # +recommendations,calendar (omitted/Tier1)
    "life_event": (),
    "general": (),
}


def files_for_intent(intent: str, member: str) -> list[str]:
    """Resolve an intent to assembler memory stems for `member`.

    Stems have no `memory/` prefix and no `.md` suffix (e.g.
    `members/vedant/goals`). Unknown intents and unknown entry names are
    skipped, yielding []."""
    stems: list[str] = []
    for name in INTENT_FILES.get(intent, ()):
        entry = entry_by_name(name)
        if entry is None:
            continue
        stem = (
            entry.path_template.removeprefix("memory/")
            .removesuffix(".md")
            .replace("{member}", member)
        )
        stems.append(stem)
    return stems
