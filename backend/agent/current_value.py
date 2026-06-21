"""
The current-value / dated-log write engine (MEMORY_DATA_MODEL §2-3, §8).

This is path-agnostic mechanics. The cross-member privacy guard lives in
`writers.py` and runs BEFORE calling here; this module only manipulates the
markdown of an already-resolved target file.

Three primitives:

- `upsert_current_value` — supersede-on-match with provenance + authority guard.
  Read-modify-write: find the matching CURRENT block by key, mark it SUPERSEDED,
  append the new CURRENT block. History is never destroyed. Idempotent via
  `dedup_id` (key+value) so a retried session close never duplicates or
  resurrects a value. A lower-authority candidate NEVER clobbers a higher one —
  it is staged to `working/discrepancies.md` instead (§3 "never clobbers an
  upload", §8 "when unsure, stage — don't assert").
- `append_dated_snapshot` — dated-log: always insert a new dated block, never
  supersede (portfolio reviews keep full history).
- `append_staging` — idempotent free-form append for `working/` staging files.

Block shape (current-value):

    ## income.salary
    - value: 100000
    - source: onboarding_form
    - confidence: high
    - as_of: 2026-06-01
    - last_updated: 2026-06-01
    - status: CURRENT
    <!-- id:<dedup_id> -->
"""
from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

from backend.agent.provenance import Provenance, authority_of
from backend.utils.markdown_io import read_markdown_or_none, write_markdown_atomic


class UpsertOutcome(Enum):
    INSERTED = "inserted"      # no prior current value → wrote new
    SUPERSEDED = "superseded"  # replaced prior current (equal/higher authority)
    NOOP = "noop"              # this exact key+value already present (idempotent)
    STAGED = "staged"          # lower-authority conflict → staged, current untouched
    ACCRUED = "accrued"        # soft update: evidence appended + confidence nudged, claim kept


_CONFIDENCE_ORDER = ("low", "med", "high")


def _bump_confidence(level: str) -> str:
    """Nudge confidence one notch, capped at high; unknown levels start at low."""
    i = _CONFIDENCE_ORDER.index(level) if level in _CONFIDENCE_ORDER else 0
    return _CONFIDENCE_ORDER[min(i + 1, len(_CONFIDENCE_ORDER) - 1)]


def _id_marker(dedup_id: str) -> str:
    return f"<!-- id:{dedup_id} -->"


def _split_blocks(content: str) -> list[str]:
    """Split content at each `## ` header, keeping the delimiter so a join is
    lossless. The first element may be preamble (frontmatter / loose text)."""
    if not content:
        return []
    return re.split(r"(?m)(?=^## )", content)


def _is_block_for(part: str, key: str) -> bool:
    return part.split("\n", 1)[0].strip() == f"## {key}"


def key_for_id(content: str, target_id: str) -> str | None:
    """Map an extractor-supplied `target_id` back to the canonical key of the
    block carrying its `<!-- id:target_id -->` marker, or None if no block has it
    (MEMORY_DATA_MODEL §16). A SUPERSEDED block keeps its marker, so the id still
    resolves. Lets an update land on the existing block's key instead of a
    parallel one — the deterministic half of agentic surgical edit."""
    if not target_id:
        return None
    marker = _id_marker(target_id)
    for part in _split_blocks(content):
        if part.startswith("## ") and marker in part:
            return part.split("\n", 1)[0][len("## "):].strip()
    return None


def strip_superseded(content: str) -> str:
    """Drop SUPERSEDED blocks for read-side display, keeping CURRENT and
    status-less blocks (preamble, dated snapshots). Superseded values are kept on
    disk as history but should not clutter the assembled prompt — the agent only
    needs the live value, the same way conversation summaries are tail-bounded."""
    if not content:
        return content
    kept = [
        part
        for part in _split_blocks(content)
        if not (part.startswith("## ") and "- status: SUPERSEDED" in part)
    ]
    return "".join(kept)


def _field(block: str, field: str) -> str:
    m = re.search(rf"(?m)^- {re.escape(field)}: (.*)$", block)
    return m.group(1).strip() if m else ""


def _norm(v: str) -> str:
    """Light value normalization for equality checks: lowercase, drop spaces,
    commas, and a leading rupee/inr marker. Deliberately conservative — never
    rounds or fuzzy-matches, so two genuinely different values stay different."""
    s = v.strip().lower().replace(",", "").replace(" ", "")
    for pre in ("rs", "inr", "₹"):
        if s.startswith(pre):
            s = s[len(pre):]
    return s


def _values_match(block: str, fields: dict[str, str]) -> bool:
    """True if every candidate field already equals the block's value (after
    normalization). A lower-authority source that merely restates the current
    value is not a conflict, so it must not be staged as a discrepancy."""
    return all(_norm(_field(block, k)) == _norm(v) for k, v in fields.items())


def _with_appended(content: str, block: str) -> str:
    """Append a block to existing content with a single blank-line separator."""
    if not content:
        return block
    if not content.endswith("\n"):
        content += "\n"
    return content + "\n" + block


def _render_block(
    header: str,
    fields: dict[str, str],
    prov: Provenance,
    dedup_id: str,
    *,
    status: str | None,
) -> str:
    lines = [f"## {header}"]
    lines += [f"- {k}: {v}" for k, v in fields.items()]
    lines += [
        f"- source: {prov.source}",
        f"- confidence: {prov.confidence}",
        f"- as_of: {prov.as_of}",
        f"- last_updated: {prov.last_updated}",
    ]
    if status is not None:
        lines.append(f"- status: {status}")
    lines.append(_id_marker(dedup_id))
    return "\n".join(lines) + "\n"


def _stage_discrepancy(
    path: Path,
    key: str,
    fields: dict[str, str],
    prov: Provenance,
    existing_source: str,
    dedup_id: str,
) -> None:
    existing = read_markdown_or_none(path) or ""
    marker = _id_marker(dedup_id)
    if marker in existing:
        return
    summary = ", ".join(f"{k}={v}" for k, v in fields.items())
    block = (
        f"## {key}\n"
        f"- candidate: {summary}\n"
        f"- candidate_source: {prov.source} ({prov.confidence})\n"
        f"- conflicts_with_source: {existing_source}\n"
        f"- as_of: {prov.as_of}\n"
        f"- status: NEEDS_CONFIRMATION\n"
        f"{marker}\n"
    )
    write_markdown_atomic(path, _with_appended(existing, block))


def upsert_current_value(
    path: Path,
    *,
    key: str,
    fields: dict[str, str],
    prov: Provenance,
    dedup_id: str,
    discrepancies_path: Path | None = None,
) -> UpsertOutcome:
    """Insert or supersede the current value for `key` in a current-value file.

    Lower-authority candidates conflicting with a higher-authority current value
    are staged (never clobber); see module docstring."""
    content = read_markdown_or_none(path) or ""
    if _id_marker(dedup_id) in content:
        return UpsertOutcome.NOOP

    parts = _split_blocks(content)
    cur_idx = next(
        (
            i
            for i, part in enumerate(parts)
            if _is_block_for(part, key) and "- status: CURRENT" in part
        ),
        None,
    )
    new_block = _render_block(key, fields, prov, dedup_id, status="CURRENT")

    if cur_idx is None:
        write_markdown_atomic(path, _with_appended(content, new_block))
        return UpsertOutcome.INSERTED

    existing_source = _field(parts[cur_idx], "source")
    if authority_of(prov.source) < authority_of(existing_source):
        # Lower authority, but if it merely restates the current value it's not a
        # conflict — skip the spurious discrepancy entirely.
        if _values_match(parts[cur_idx], fields):
            return UpsertOutcome.NOOP
        if discrepancies_path is not None:
            _stage_discrepancy(
                discrepancies_path, key, fields, prov, existing_source, dedup_id
            )
        return UpsertOutcome.STAGED

    parts[cur_idx] = parts[cur_idx].replace(
        "- status: CURRENT", "- status: SUPERSEDED", 1
    )
    write_markdown_atomic(path, _with_appended("".join(parts), new_block))
    return UpsertOutcome.SUPERSEDED


def accrue_evidence(
    path: Path,
    *,
    key: str,
    fields: dict[str, str],
    prov: Provenance,
    dedup_id: str,
    evidence: str,
) -> UpsertOutcome:
    """Soft update for the inference layer (MEMORY_DATA_MODEL §10).

    Insert the claim if its topic is absent; otherwise ACCRUE — append an
    evidence line, nudge confidence one notch, and advance last_updated, while
    leaving the claim itself UNTOUCHED. A behavioral read therefore never flips
    on a single remark; the trajectory accumulates as evidence. Idempotent via
    dedup_id. `fields` (e.g. {"claim": ...} or {"stance": ...}) is used only when
    inserting a fresh topic."""
    content = read_markdown_or_none(path) or ""
    marker = _id_marker(dedup_id)
    if marker in content:
        return UpsertOutcome.NOOP

    parts = _split_blocks(content)
    cur_idx = next(
        (
            i
            for i, part in enumerate(parts)
            if _is_block_for(part, key) and "- status: CURRENT" in part
        ),
        None,
    )

    if cur_idx is None:
        block = _render_block(key, fields, prov, dedup_id, status="CURRENT")
        write_markdown_atomic(path, _with_appended(content, block))
        return UpsertOutcome.INSERTED

    block = parts[cur_idx]
    cur_conf = _field(block, "confidence")
    if cur_conf:
        block = block.replace(
            f"- confidence: {cur_conf}", f"- confidence: {_bump_confidence(cur_conf)}", 1
        )
    cur_lu = _field(block, "last_updated")
    if cur_lu:
        block = block.replace(
            f"- last_updated: {cur_lu}", f"- last_updated: {prov.last_updated}", 1
        )
    block = block.rstrip("\n") + f"\n- evidence: {evidence} ({prov.as_of}) {marker}\n"
    parts[cur_idx] = block
    write_markdown_atomic(path, "".join(parts))
    return UpsertOutcome.ACCRUED


def append_dated_snapshot(
    path: Path,
    *,
    as_of: str,
    fields: dict[str, str],
    prov: Provenance,
    dedup_id: str,
) -> bool:
    """Append a full dated snapshot (dated-log mode). Idempotent via dedup_id.
    Returns True if written, False if the snapshot was already present."""
    content = read_markdown_or_none(path) or ""
    if _id_marker(dedup_id) in content:
        return False
    block = _render_block(f"as of {as_of}", fields, prov, dedup_id, status=None)
    write_markdown_atomic(path, _with_appended(content, block))
    return True


def append_staging(path: Path, *, entry: str, dedup_id: str) -> bool:
    """Append a free-form, idempotent line to a `working/` staging file.
    Returns True if written, False if already present."""
    content = read_markdown_or_none(path) or ""
    marker = _id_marker(dedup_id)
    if marker in content:
        return False
    write_markdown_atomic(path, _with_appended(content, f"- {entry} {marker}\n"))
    return True
