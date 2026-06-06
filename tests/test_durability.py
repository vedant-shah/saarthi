"""
Tests for backend.agent.durability — session-end durability fix.

TDD: written FIRST (RED), then implementation added to make them GREEN.

Conventions mirror test_memory_updater.py:
- asyncio_mode = "auto" (pyproject), no @pytest.mark.asyncio needed
- `tmp_memory` + `fake_provider` fixtures from conftest.py
- autouse fixture resets memory_updater._provider
- local helpers build transcripts with controllable `ts` fields
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.agent import durability, memory_updater, sessions
from backend.agent.transcripts import transcript_path
from backend.config import settings


# ---------------------------------------------------------------------------
# Autouse: reset provider and in-memory session state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_state():
    """Reset memory_updater._provider and all session in-memory state."""
    memory_updater._provider = None
    # Clear all in-memory session state so tests are fully isolated
    sessions._active.clear()
    sessions._activity.clear()
    sessions._history.clear()
    yield
    memory_updater._provider = None
    sessions._active.clear()
    sessions._activity.clear()
    sessions._history.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_transcript(member: str, session_id: str, ts: str, extra_lines: int = 0) -> Path:
    """Write a JSONL transcript with the given ISO timestamp on the last line.

    `ts` is injected verbatim into the JSON so tests control wall-clock age.
    `extra_lines` prepend earlier lines with a different ts so last-line logic
    is exercised.
    """
    path = transcript_path(member, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(extra_lines):
        earlier = {"ts": "2000-01-01T00:00:00.000Z", "user_msg": f"msg{i}", "assistant_msg": "ok"}
        lines.append(json.dumps(earlier))
    lines.append(json.dumps({"ts": ts, "user_msg": "hello", "assistant_msg": "world"}))
    path.write_text("\n".join(lines) + "\n")
    return path


def _stale_ts(now: datetime, extra_seconds: int = 60) -> str:
    """Return an ISO ts string that is STALE_AFTER_SECONDS + extra_seconds before now."""
    delta = timedelta(seconds=sessions.STALE_AFTER_SECONDS + extra_seconds)
    return (now - delta).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _fresh_ts(now: datetime, seconds_ago: int = 60) -> str:
    """Return an ISO ts string that is seconds_ago before now (still fresh)."""
    return (now - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 1. last_message_ts — reads LAST line's ts correctly
# ---------------------------------------------------------------------------

async def test_last_message_ts_returns_last_line(tmp_memory):
    now = _now_utc()
    ts_str = "2024-03-15T10:30:00.000Z"
    _write_transcript("vedant", "s1", ts=ts_str, extra_lines=3)

    result = durability.last_message_ts("vedant", "s1")

    assert result is not None
    assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 2. last_message_ts — returns None for bad inputs (never raises)
# ---------------------------------------------------------------------------

async def test_last_message_ts_missing_file(tmp_memory):
    result = durability.last_message_ts("vedant", "nonexistent")
    assert result is None


async def test_last_message_ts_empty_file(tmp_memory):
    path = transcript_path("vedant", "s_empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")

    result = durability.last_message_ts("vedant", "s_empty")
    assert result is None


async def test_last_message_ts_malformed_json(tmp_memory):
    path = transcript_path("vedant", "s_bad")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all\n")

    result = durability.last_message_ts("vedant", "s_bad")
    assert result is None


async def test_last_message_ts_missing_ts_field(tmp_memory):
    path = transcript_path("vedant", "s_nots")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"user_msg": "hello", "assistant_msg": "world"}) + "\n")

    result = durability.last_message_ts("vedant", "s_nots")
    assert result is None


# ---------------------------------------------------------------------------
# 3. Crash case: stale transcript, no .closed marker → summarized exactly once
# ---------------------------------------------------------------------------

async def test_stale_unclosed_session_is_summarized(tmp_memory, fake_provider):
    fake_provider.payload = {"summary_3_lines": ["stale", "but", "closed"]}
    memory_updater._provider = fake_provider

    now = _now_utc()
    ts = _stale_ts(now)
    _write_transcript("vedant", "sess_stale", ts=ts)

    count = await durability.scan_and_close_stale(now)

    assert count == 1
    assert fake_provider.calls == 1
    conv = (tmp_memory / "members" / "vedant" / "conversations.md").read_text()
    assert "stale" in conv
    marker = settings.resolve(settings.sessions_dir) / "vedant" / "sess_stale.closed"
    assert marker.exists()


# ---------------------------------------------------------------------------
# 4. Sleep case: one stale, one fresh → only stale is closed
# ---------------------------------------------------------------------------

async def test_stale_closed_fresh_untouched(tmp_memory, fake_provider):
    fake_provider.payload = {"summary_3_lines": ["summarized"]}
    memory_updater._provider = fake_provider

    now = _now_utc()
    _write_transcript("vedant", "sess_old", ts=_stale_ts(now))
    _write_transcript("vedant", "sess_new", ts=_fresh_ts(now, seconds_ago=60))

    count = await durability.scan_and_close_stale(now)

    assert count == 1
    assert fake_provider.calls == 1
    # stale: closed
    marker_old = settings.resolve(settings.sessions_dir) / "vedant" / "sess_old.closed"
    assert marker_old.exists()
    # fresh: no marker
    marker_new = settings.resolve(settings.sessions_dir) / "vedant" / "sess_new.closed"
    assert not marker_new.exists()


# ---------------------------------------------------------------------------
# 5. Across users: stale sessions under MULTIPLE member dirs all closed
# ---------------------------------------------------------------------------

async def test_scan_covers_multiple_members(tmp_memory, fake_provider):
    fake_provider.payload = {"summary_3_lines": ["done"]}
    memory_updater._provider = fake_provider

    now = _now_utc()
    # Both members already exist in tmp_memory fixture (vedant, mom)
    _write_transcript("vedant", "sv1", ts=_stale_ts(now))
    _write_transcript("mom", "sm1", ts=_stale_ts(now))

    count = await durability.scan_and_close_stale(now)

    assert count == 2
    assert fake_provider.calls == 2
    assert (settings.resolve(settings.sessions_dir) / "vedant" / "sv1.closed").exists()
    assert (settings.resolve(settings.sessions_dir) / "mom" / "sm1.closed").exists()


# ---------------------------------------------------------------------------
# 6. Idempotency: running scan twice → exactly one summary, one provider call
# ---------------------------------------------------------------------------

async def test_scan_idempotent(tmp_memory, fake_provider):
    fake_provider.payload = {"summary_3_lines": ["once"]}
    memory_updater._provider = fake_provider

    now = _now_utc()
    _write_transcript("vedant", "sess_idem", ts=_stale_ts(now))

    await durability.scan_and_close_stale(now)
    count2 = await durability.scan_and_close_stale(now)

    assert count2 == 0  # second run: marker present, nothing to do
    assert fake_provider.calls == 1  # provider called exactly once total


# ---------------------------------------------------------------------------
# 7. Already-closed transcript → scan skips it
# ---------------------------------------------------------------------------

async def test_already_closed_skipped(tmp_memory, fake_provider):
    memory_updater._provider = fake_provider

    now = _now_utc()
    _write_transcript("vedant", "sess_pre", ts=_stale_ts(now))
    # Pre-place the marker
    marker = settings.resolve(settings.sessions_dir) / "vedant" / "sess_pre.closed"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()

    count = await durability.scan_and_close_stale(now)

    assert count == 0
    assert fake_provider.calls == 0


# ---------------------------------------------------------------------------
# 8. evict_if_active: correct/incorrect session_id and missing member
# ---------------------------------------------------------------------------

def test_evict_if_active_matches_evicts(tmp_memory):
    sessions._active["vedant"] = "sid-abc"
    sessions._activity[("vedant", "sid-abc")] = 1.0
    sessions._history[("vedant", "sid-abc")] = [{"role": "user", "content": "hi"}]

    result = sessions.evict_if_active("vedant", "sid-abc")

    assert result is True
    assert "vedant" not in sessions._active
    assert ("vedant", "sid-abc") not in sessions._activity
    assert ("vedant", "sid-abc") not in sessions._history


def test_evict_if_active_wrong_sid_leaves_state(tmp_memory):
    sessions._active["vedant"] = "sid-live"
    sessions._activity[("vedant", "sid-live")] = 1.0
    sessions._history[("vedant", "sid-live")] = [{"role": "user", "content": "hi"}]

    result = sessions.evict_if_active("vedant", "sid-old")

    assert result is False
    # Live session must remain untouched
    assert sessions._active["vedant"] == "sid-live"
    assert ("vedant", "sid-live") in sessions._activity


def test_evict_if_active_absent_member(tmp_memory):
    result = sessions.evict_if_active("nobody", "any-sid")
    assert result is False


# ---------------------------------------------------------------------------
# 9. Concurrency: two concurrent close_session calls → provider called once
# ---------------------------------------------------------------------------

async def test_concurrent_close_calls_provider_once(tmp_memory, fake_provider):
    """TOCTOU lock test: two concurrent closers converge — only one goes through."""
    fake_provider.payload = {"summary_3_lines": ["concurrent"]}
    memory_updater._provider = fake_provider

    _write_transcript("vedant", "sess_conc", ts=_stale_ts(_now_utc()))

    # Fire both concurrently
    await asyncio.gather(
        memory_updater.close_session("vedant", "sess_conc"),
        memory_updater.close_session("vedant", "sess_conc"),
    )

    assert fake_provider.calls == 1
    marker = settings.resolve(settings.sessions_dir) / "vedant" / "sess_conc.closed"
    assert marker.exists()
