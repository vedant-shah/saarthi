"""
Session-end summarizer — idempotent persistence of conversation outcomes.

`close_session` is the single convergence point for both close triggers (the
`/session/close` beacon and the 60s idle sweep). It reads the session JSONL
transcript, asks Haiku to extract durable outcomes via a forced `summarize`
tool, and dispatches each to the matching writer with `writer=member` (so
cross-member isolation holds even if the model hallucinates another member).

Idempotency gate: a `<session_id>.closed` marker. If present, this is a no-op —
the beacon and the scheduler may both fire for the same session. On success the
marker is written last; on exception it is NOT written, so a retry can recover.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

from backend.agent.llm_provider import LLMProvider, SystemBlock, get_provider
from backend.agent.transcripts import transcript_path
from backend.agent.writers import (
    append_conversation_summary,
    record_status_transition,
    write_goal,
    write_life_event,
    write_recommendation,
)
from backend.config import settings
from backend.utils.markdown_io import marker_exists, read_markdown_or_none, touch_marker

logger = logging.getLogger(__name__)

_DEFAULT_PRIORITY = 2

_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider:
    """Lazy module-level provider so close_session does not need one injected."""
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


_SUMMARIZER_SYSTEM = (
    "You are summarizing a closed advisory session for durable memory. Extract "
    "only what was actually established this session — do not invent. Produce a "
    "concise 3-line summary plus any new recommendations, goals, stated life "
    "events, and status changes that the family member and advisor agreed on."
)

_SUMMARIZE_TOOL = {
    "name": "summarize",
    "description": "Extract durable outcomes from the session transcript.",
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
            "new_goals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "target": {"type": "string"},
                        "horizon": {"type": "string"},
                    },
                    "required": ["title"],
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


def marker_path(member: str, session_id: str) -> Path:
    return settings.resolve(settings.sessions_dir) / member / f"{session_id}.closed"


# Per-session async locks preventing TOCTOU on the check-summarize-mark body.
# Lazily created; keyed by (member, session_id).
_session_locks: dict[tuple[str, str], asyncio.Lock] = {}


def _lock_for(member: str, session_id: str) -> asyncio.Lock:
    # setdefault is atomic at the dict level, so concurrent callers for the same
    # session always get the same lock without a check-then-set race.
    return _session_locks.setdefault((member, session_id), asyncio.Lock())


def _safe(label: str, fn) -> None:
    """Run one writer dispatch, logging and swallowing its error so a single bad
    entry never aborts the rest of the session's persistence."""
    try:
        fn()
    except Exception:
        logger.exception("memory_updater: writer failed (%s)", label)


def _dispatch(member: str, raw: dict, today: str) -> None:
    """Route summarizer output to the per-file writers. All writes use
    writer=member so isolation holds regardless of model output."""
    summary_lines = raw.get("summary_3_lines") or []
    if summary_lines:
        _safe(
            "conversation_summary",
            lambda: append_conversation_summary(member, date=today, summary_lines=summary_lines),
        )

    for rec in raw.get("new_recommendations", []):
        _safe(
            "recommendation",
            lambda rec=rec: write_recommendation(
                member,
                title=rec["title"],
                priority=rec.get("priority", _DEFAULT_PRIORITY),
                body=rec.get("assumptions", ""),
                date=today,
            ),
        )

    for goal in raw.get("new_goals", []):
        _safe(
            "goal",
            lambda goal=goal: write_goal(
                member,
                title=goal["title"],
                target=goal.get("target", ""),
                horizon=goal.get("horizon", ""),
                date=today,
            ),
        )

    for event in raw.get("life_events_stated", []):
        _safe("life_event", lambda event=event: write_life_event(member, description=event, date=today))

    for transition in raw.get("status_transitions", []):
        _safe(
            "status_transition",
            lambda t=transition: record_status_transition(
                member,
                item=t["item"],
                from_status=t["from_status"],
                to_status=t["to_status"],
                date=today,
            ),
        )


async def close_session(member: str, session_id: str) -> None:
    """Summarize and persist a closed session. Idempotent via the .closed marker.

    No-op if already closed. If there is no transcript, only the marker is
    written. On any failure, the marker is NOT written so the close can retry.

    The per-session async lock closes the TOCTOU window: two concurrent callers
    (startup scan + idle sweep + beacon) both pass the initial marker check
    before either writes, but only one proceeds through the summarizer. The
    marker is written LAST (after the network call) so a crash mid-summarize
    leaves the session retryable."""
    async with _lock_for(member, session_id):
        marker = marker_path(member, session_id)
        if marker_exists(marker):
            logger.info("memory_updater: already closed %s/%s", member, session_id)
            return

        content = read_markdown_or_none(transcript_path(member, session_id))
        if content is None:
            logger.info("memory_updater: no transcript %s/%s — marking closed", member, session_id)
            touch_marker(marker)
            return

        raw = await _get_provider().complete_json(
            system=[SystemBlock(text=_SUMMARIZER_SYSTEM)],
            messages=[{"role": "user", "content": content}],
            tool=_SUMMARIZE_TOOL,
            model=settings.summarizer_model,
            max_tokens=1024,
        )

        today = date.today().isoformat()
        _dispatch(member, raw, today)

        touch_marker(marker)
        logger.info("memory_updater: closed %s/%s", member, session_id)
