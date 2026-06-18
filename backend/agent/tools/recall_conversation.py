"""The `recall_conversation` handler: keyword-search older transcripts.

The recent session summaries are already preloaded; this reaches further back
into the verbatim turn history for the ACTIVE member only (the member is taken
from the session, never the model). Returns dated excerpts of the best-matching
past turns, capped so it never blows the token budget. A search that finds
nothing is a successful empty result; only an empty query is an error.
"""
from __future__ import annotations

import json
from typing import Iterator

from backend.agent.tools.dispatch import ToolResult
from backend.config import settings

_MAX_RESULTS = 6
_USER_CLIP = 160
_ASSISTANT_CLIP = 320


def _iter_turns(member: str) -> Iterator[tuple[str, str, str]]:
    base = settings.resolve(settings.sessions_dir) / member
    if not base.is_dir():
        return
    for path in sorted(base.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict) or rec.get("type") == "post_processing":
                continue
            user = (rec.get("user_msg") or "").strip()
            assistant = (rec.get("assistant_msg") or "").strip()
            if user or assistant:
                yield rec.get("ts", ""), user, assistant


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def handle_recall_conversation(tool_input: dict, active_member: str) -> ToolResult:
    query = (tool_input.get("query") or "").strip()
    if not query:
        return ToolResult(
            "[tool error] recall_conversation needs a search query", ok=False
        )

    terms = [t.lower() for t in query.split()]
    scored: list[tuple[int, str, str, str]] = []
    for ts, user, assistant in _iter_turns(active_member):
        haystack = f"{user} {assistant}".lower()
        score = sum(1 for t in terms if t in haystack)
        if score:
            scored.append((score, ts, user, assistant))

    if not scored:
        return ToolResult(f'no past conversations matched "{query}".', ok=True)

    # Best match first; ISO timestamps sort lexicographically, so most recent
    # breaks ties.
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    lines: list[str] = []
    for _score, ts, user, assistant in scored[:_MAX_RESULTS]:
        date = ts[:10] if ts else "unknown date"
        lines.append(
            f"[{date}] you: {_clip(user, _USER_CLIP)}\n"
            f"advisor: {_clip(assistant, _ASSISTANT_CLIP)}"
        )
    return ToolResult("\n\n".join(lines), ok=True)
