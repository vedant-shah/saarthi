"""
Process-local session lifecycle + in-session history store.

Backend owns active session identity. There is at most one active session per
member. Clients do not need to track session_id — every `/chat` call resolves
to "the active session for this member" (creating a fresh one if absent or
stale). The session_id is still returned to clients in the `done` event for
display/debugging.

State is module-level and wiped on process restart — JSONL transcripts are the
durable record (Day 2 M3). Safe for a single async worker under CPython's GIL;
breaks under multi-worker or threaded execution (move to Redis if we scale).

Conventions:
- Timestamps are `time.monotonic()` values supplied by the caller (not wall
  clock — monotonic clocks are immune to NTP adjustments).
- `resolve_session` self-registers a newly minted session with `now` so it can
  be looked up immediately. Callers still must call `touch` on every
  subsequent turn to keep the session fresh.
- `get_history` returns a copy of the outer list. History entries are treated
  as immutable downstream; do not mutate the returned dicts.
"""
from __future__ import annotations

import uuid

_active: dict[str, str] = {}
_activity: dict[tuple[str, str], float] = {}
_history: dict[tuple[str, str], list[dict]] = {}

STALE_AFTER_SECONDS = 30 * 60


def is_stale(last_ts: float, now: float) -> bool:
    return now - last_ts > STALE_AFTER_SECONDS


def _clear_member(member: str) -> None:
    sid = _active.pop(member, None)
    if sid is not None:
        _activity.pop((member, sid), None)
        _history.pop((member, sid), None)


def resolve_session(member: str, now: float) -> tuple[str, bool]:
    """Return (active_session_id, is_new) for `member`.

    Looks up the member's current active session. Returns it when fresh.
    Otherwise mints a new UUID, registers it as the active session, and
    returns (new_sid, True). Clients never supply a session_id — the backend
    is the single source of truth for active session identity."""
    current = _active.get(member)
    if current is not None:
        last_ts = _activity.get((member, current))
        if last_ts is not None and not is_stale(last_ts, now):
            return current, False
    _clear_member(member)
    new_sid = str(uuid.uuid4())
    _active[member] = new_sid
    _activity[(member, new_sid)] = now
    return new_sid, True


def get_active(member: str, now: float) -> str | None:
    """Return the active session_id for `member`, or None if none/stale.

    If the active session is past the staleness threshold, evict it before
    returning None so subsequent `resolve_session` calls don't have to
    re-detect and clean up. Keeps `/api/history` and `/chat` in lockstep."""
    sid = _active.get(member)
    if sid is None:
        return None
    last_ts = _activity.get((member, sid))
    if last_ts is None or is_stale(last_ts, now):
        _clear_member(member)
        return None
    return sid


def touch(member: str, session_id: str, now: float) -> None:
    _activity[(member, session_id)] = now


def append_history(member: str, session_id: str, role: str, content: str) -> None:
    _history.setdefault((member, session_id), []).append({"role": role, "content": content})


def get_history(member: str, session_id: str) -> list[dict]:
    """Return a shallow copy of the message list (safe to iterate / append to)."""
    return list(_history.get((member, session_id), []))


def evict_if_active(member: str, session_id: str) -> bool:
    """Clear in-memory routing state for `member` ONLY if `session_id` is
    currently the active session. Returns True if eviction happened.

    The session_id guard prevents nuking a fresh session that the live process
    may have started since the disk-based scan identified the stale one."""
    if _active.get(member) != session_id:
        return False
    _clear_member(member)
    return True


def close(member: str) -> bool:
    """Close the active session for `member`. Idempotent.
    Returns True if there was an active session to close."""
    existed = member in _active
    _clear_member(member)
    return existed
