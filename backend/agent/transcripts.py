"""
Transcript persistence — single chokepoint for JSONL turn append.

The TranscriptRecord schema evolves append-only: new fields are added with safe
defaults so older lines and readers keep working.
  - `intent` defaults to "unknown" until the classifier populates it.
  - `tool_calls` defaults to () until the tool loop populates it.
  - observability fields (context_level, loaded_context, model, token usage,
    latency, cost, stop_reason, error) default until the pipeline populates them.

Only this module may call `markdown_io.append_jsonl` (greppable invariant).

Post-processing status is recorded as a terminal event appended to the same
transcript (no sibling marker file): the durable JSONL is the single source of
truth for both last-activity time and whether the session was summarized.
"""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.utils.markdown_io import append_jsonl

logger = logging.getLogger(__name__)

# Soft tripwire on line size. On local filesystems an O_APPEND write is atomic
# regardless of length (PIPE_BUF only bounds atomicity for pipes/FIFOs), and the
# only concurrent writers here are one request handler and the durability sweep.
# Richer observability lines routinely exceed the old 4096 cap, so this is a
# generous warn-only ceiling, not a hard limit.
_MAX_LINE_BYTES = 32768


@dataclass(frozen=True)
class TranscriptRecord:
    ts: str
    member: str
    session_id: str
    turn_id: str
    user_msg: str
    assistant_msg: str
    tool_calls: tuple[dict, ...] = ()
    intent: str = "unknown"
    # Observability fields (appended over time; all default so older records and
    # readers keep working). These let a weekly audit explain *why* a turn
    # behaved as it did: what the agent knew, what its tools returned, what the
    # model cost, and whether the turn errored.
    context_level: str = "unknown"
    loaded_context: tuple[str, ...] = ()  # memory/skill files in the prompt this turn
    missing_context: tuple[str, ...] = ()  # optional files that were absent
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    stop_reason: str = ""
    error: str | None = None
    # Swipe-to-reply: the message the user was replying to, and who said it
    # ("assistant" = the advisor, else their own). Recorded so the audit and the
    # extractor can see exactly what a reply was responding to.
    quoted_text: str | None = None
    quoted_role: str = ""


def now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def transcript_path(member: str, session_id: str) -> Path:
    return settings.resolve(settings.sessions_dir) / member / f"{session_id}.jsonl"


def turn_id_for(history_len: int) -> str:
    return f"t{history_len // 2 + 1:02d}"


_POST_PROCESSING_TYPE = "post_processing"
_COMPLETED_STATUS = "completed"


def mark_post_processed(member: str, session_id: str) -> None:
    """Append a terminal post-processing-completed event to the transcript.

    This is the durable 'done' signal that replaces the old `.closed` marker
    file. Written LAST in close_session, after all entities persist, so a crash
    mid-summarize leaves no completed event and the catch-up scan retries."""
    record = {
        "type": _POST_PROCESSING_TYPE,
        "status": _COMPLETED_STATUS,
        "ts": now_iso(),
    }
    append_jsonl(transcript_path(member, session_id), record)


def is_post_processed(member: str, session_id: str) -> bool:
    """True if the transcript contains a completed post-processing event.

    Never raises — returns False on any error (missing file, unreadable, a
    malformed/torn line). A torn terminal line therefore reads as 'not done',
    which is the safe direction (the scan will retry)."""
    path = transcript_path(member, session_id)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(record, dict)
            and record.get("type") == _POST_PROCESSING_TYPE
            and record.get("status") == _COMPLETED_STATUS
        ):
            return True
    return False


def append_turn(record: TranscriptRecord) -> None:
    """Append one JSONL line. Errors are logged and swallowed."""
    try:
        as_dict = dataclasses.asdict(record)
        as_dict["tool_calls"] = list(record.tool_calls)
        as_dict["loaded_context"] = list(record.loaded_context)
        as_dict["missing_context"] = list(record.missing_context)
        line_bytes = len(json.dumps(as_dict, ensure_ascii=False).encode("utf-8"))
        if line_bytes > _MAX_LINE_BYTES:
            logger.warning(
                "transcript line %d > %d bytes: %s/%s/%s",
                line_bytes,
                _MAX_LINE_BYTES,
                record.member,
                record.session_id,
                record.turn_id,
            )
        append_jsonl(transcript_path(record.member, record.session_id), as_dict)
    except Exception:
        logger.exception(
            "transcript append failed: %s/%s/%s",
            record.member,
            record.session_id,
            record.turn_id,
        )
