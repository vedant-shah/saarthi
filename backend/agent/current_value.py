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


def _field(block: str, field: str) -> str:
    m = re.search(rf"(?m)^- {re.escape(field)}: (.*)$", block)
    return m.group(1).strip() if m else ""


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
