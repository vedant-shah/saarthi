"""
Per-file memory writers, guarded by cross-member write isolation.

This is the privacy enforcement point (PRD Decision #27): a writer acting as
member X may only write under `memory/members/X/` or the shared `memory/family/`
tree. `_assert_writable` runs FIRST in every public writer, so a summarizer that
hallucinates another member's path is rejected before any bytes are written.

Greppable invariant: this module never opens files directly — every write
routes through `markdown_io` helpers.

Idempotency: pass a `dedup_id` to make a write skip-if-already-present, so a
retried session close never duplicates entities that already landed.
"""
from __future__ import annotations

import logging
from pathlib import Path

from backend.agent.current_value import (
    UpsertOutcome,
    append_dated_snapshot,
    append_staging,
    upsert_current_value,
)
from backend.agent.provenance import Provenance
from backend.config import settings
from backend.utils.markdown_io import append_markdown, read_markdown_or_none

logger = logging.getLogger(__name__)


class CrossMemberWriteError(Exception):
    """Raised when a writer attempts to write outside its own member tree or the
    shared family tree."""


def _assert_writable(writer: str, target: Path) -> None:
    root = settings.resolve(settings.memory_dir).resolve()
    # members/<writer> is the writer's own tree; family/ and working/ are shared
    # destinations (joint facts and staging) permitted to any writer.
    allowed = (root / "members" / writer, root / "family", root / "working")
    resolved = target.resolve()
    if not any(
        resolved == a or a in resolved.parents for a in (a.resolve() for a in allowed)
    ):
        raise CrossMemberWriteError(f"{writer} cannot write {resolved}")


def _member_file(writer: str, fname: str) -> Path:
    return settings.resolve(settings.memory_dir) / "members" / writer / fname


def _working_file(fname: str) -> Path:
    return settings.resolve(settings.memory_dir) / "working" / fname


def _id_marker(dedup_id: str) -> str:
    return f"<!-- id:{dedup_id} -->"


def _append_entry(writer: str, path: Path, entry: str, dedup_id: str | None) -> None:
    """Write one entry, guarded by cross-member isolation.

    When `dedup_id` is given the entry is idempotent: if a marker for that id is
    already in the file the write is skipped, so re-running a session close never
    duplicates entities that already landed. The marker is embedded in the entry
    so it persists for the next check."""
    _assert_writable(writer, path)
    if dedup_id is None:
        append_markdown(path, entry)
        return
    marker = _id_marker(dedup_id)
    existing = read_markdown_or_none(path)
    if existing is not None and marker in existing:
        return
    append_markdown(path, f"\n{marker}{entry}")


def write_recommendation(
    writer: str,
    *,
    title: str,
    priority: int,
    body: str,
    date: str,
    dedup_id: str | None = None,
) -> None:
    """Append a PROPOSED recommendation to the writer's recommendations.md."""
    p = _member_file(writer, "recommendations.md")
    entry = (
        f"\n## {title}\n"
        f"- Date: {date}\n"
        f"- Priority: P{priority}\n"
        f"- Status: PROPOSED\n"
        f"- Assumptions_at_time: {body}\n"
    )
    _append_entry(writer, p, entry, dedup_id)


def write_goal(
    writer: str,
    *,
    title: str,
    target: str,
    horizon: str,
    date: str,
    dedup_id: str | None = None,
) -> None:
    """Append a goal to the writer's goals.md."""
    p = _member_file(writer, "goals.md")
    entry = (
        f"\n## {title}\n"
        f"- Date: {date}\n"
        f"- Target: {target}\n"
        f"- Horizon: {horizon}\n"
        f"- Status: ACTIVE\n"
    )
    _append_entry(writer, p, entry, dedup_id)


def write_life_event(
    writer: str, *, description: str, date: str, dedup_id: str | None = None
) -> None:
    """Append a stated life event to the writer's life_events.md."""
    p = _member_file(writer, "life_events.md")
    entry = f"\n- {date}: {description}\n"
    _append_entry(writer, p, entry, dedup_id)


def append_conversation_summary(
    writer: str, *, date: str, summary_lines: list[str], dedup_id: str | None = None
) -> None:
    """Append a dated block of summary lines to the writer's conversations.md."""
    p = _member_file(writer, "conversations.md")
    lines = "".join(f"- {line}\n" for line in summary_lines)
    entry = f"\n## {date}\n{lines}"
    _append_entry(writer, p, entry, dedup_id)


def record_status_transition(
    writer: str,
    *,
    item: str,
    from_status: str,
    to_status: str,
    date: str,
    dedup_id: str | None = None,
) -> None:
    """Append a recommendation/goal status transition to agent_notes.md."""
    p = _member_file(writer, "agent_notes.md")
    entry = f"\n- {date}: {item} — {from_status} → {to_status}\n"
    _append_entry(writer, p, entry, dedup_id)


# --- current-value / dated-log / staging writers (MEMORY_DATA_MODEL §3-§7) ---
#
# Each runs `_assert_writable` FIRST, then delegates to the path-agnostic engine
# in `current_value.py`. Provenance (source/confidence/as_of/last_updated) is
# stamped on every entry; `last_updated` defaults to `as_of` when not supplied.


def write_financial_fact(
    writer: str,
    *,
    key: str,
    value: str,
    category: str,
    cadence: str,
    source: str,
    confidence: str,
    as_of: str,
    last_updated: str | None = None,
    dedup_id: str,
) -> UpsertOutcome:
    """Upsert one cash-flow/debt fact into finances.md (current-value).

    `key` is the stable identity (e.g. `income.salary`, `expense.rent`,
    `liability.home_loan`). A lower-authority conflicting value is staged to
    working/discrepancies.md rather than clobbering a higher-authority value."""
    p = _member_file(writer, "finances.md")
    _assert_writable(writer, p)
    prov = Provenance(
        source=source, confidence=confidence, as_of=as_of, last_updated=last_updated or as_of
    )
    return upsert_current_value(
        p,
        key=key,
        fields={"value": value, "category": category, "cadence": cadence},
        prov=prov,
        dedup_id=dedup_id,
        discrepancies_path=_working_file("discrepancies.md"),
    )


def write_portfolio_snapshot(
    writer: str,
    *,
    as_of: str,
    holdings: dict[str, str],
    source: str,
    confidence: str,
    last_updated: str | None = None,
    dedup_id: str,
) -> bool:
    """Append a full dated holdings snapshot to portfolio_snapshots.md (dated-log)."""
    p = _member_file(writer, "portfolio_snapshots.md")
    _assert_writable(writer, p)
    prov = Provenance(
        source=source, confidence=confidence, as_of=as_of, last_updated=last_updated or as_of
    )
    return append_dated_snapshot(
        p, as_of=as_of, fields=holdings, prov=prov, dedup_id=dedup_id
    )


def write_inference(
    writer: str,
    *,
    topic: str,
    claim: str,
    basis: str,
    confidence: str,
    as_of: str,
    source: str = "inference",
    last_updated: str | None = None,
    dedup_id: str,
) -> UpsertOutcome:
    """Upsert a behavioral inference into inferences.md (current-value), keyed by
    topic. Soft-update accrual (§10) is the reconciler's job; this is the
    mechanism it calls when it decides the claim itself should change."""
    p = _member_file(writer, "inferences.md")
    _assert_writable(writer, p)
    prov = Provenance(
        source=source, confidence=confidence, as_of=as_of, last_updated=last_updated or as_of
    )
    return upsert_current_value(
        p, key=topic, fields={"claim": claim, "basis": basis}, prov=prov, dedup_id=dedup_id
    )


def write_risk_profile(
    writer: str,
    *,
    dimension: str,
    stance: str,
    basis: str,
    confidence: str,
    as_of: str,
    source: str = "conversation",
    last_updated: str | None = None,
    dedup_id: str,
) -> UpsertOutcome:
    """Upsert a revealed risk stance into risk_profile.md (current-value), keyed
    by dimension (e.g. `risk_tolerance`, `horizon`)."""
    p = _member_file(writer, "risk_profile.md")
    _assert_writable(writer, p)
    prov = Provenance(
        source=source, confidence=confidence, as_of=as_of, last_updated=last_updated or as_of
    )
    return upsert_current_value(
        p, key=dimension, fields={"stance": stance, "basis": basis}, prov=prov, dedup_id=dedup_id
    )


def stage_cross_member_observation(
    writer: str, *, observation: str, about: str, date: str, dedup_id: str
) -> bool:
    """Stage an observation one member's session made about another member to
    working/cross_member_observations.md. Never writes the other member's tree
    (§7): promoted only on confirmation at that member's next session."""
    p = _working_file("cross_member_observations.md")
    entry = f"{date} — (via {writer}, about {about}): {observation}"
    return append_staging(p, entry=entry, dedup_id=dedup_id)
