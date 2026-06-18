"""recall_conversation tool: keyword-search the member's older transcripts.

The recent session summaries are already preloaded; this tool reaches further
back into the verbatim turn history, for the ACTIVE member only. A search that
finds nothing is a successful empty result, not an error; an empty query is the
only error case.
"""
from __future__ import annotations

import json

from backend.agent.tools.dispatch import default_dispatch
from backend.agent.tools.recall_conversation import handle_recall_conversation
from backend.config import settings


def _write_turns(sessions_dir, member, session_id, turns):
    d = sessions_dir / member
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{session_id}.jsonl").open("w", encoding="utf-8") as f:
        for ts, user, assistant in turns:
            f.write(
                json.dumps(
                    {
                        "ts": ts,
                        "member": member,
                        "session_id": session_id,
                        "turn_id": "t01",
                        "user_msg": user,
                        "assistant_msg": assistant,
                        "tool_calls": [],
                        "intent": "unknown",
                    }
                )
                + "\n"
            )


def test_recall_finds_matching_older_turn(tmp_memory):
    sessions_dir = settings.resolve(settings.sessions_dir)
    _write_turns(
        sessions_dir,
        "vedant",
        "old",
        [
            (
                "2026-02-01T10:00:00.000Z",
                "should i prepay my home loan?",
                "i'd keep the SIP running and not rush the prepay",
            ),
            ("2026-02-01T10:05:00.000Z", "whats for lunch", "not my department"),
        ],
    )
    result = handle_recall_conversation({"query": "home loan prepay"}, "vedant")
    assert result.ok
    assert "home loan" in result.content.lower()
    assert "2026-02-01" in result.content
    assert "lunch" not in result.content.lower()  # non-matching turn excluded


def test_recall_scoped_to_active_member(tmp_memory):
    sessions_dir = settings.resolve(settings.sessions_dir)
    _write_turns(
        sessions_dir, "mom", "s", [("2026-01-01T00:00:00.000Z", "my fixed deposit", "mom FD chat")]
    )
    _write_turns(
        sessions_dir,
        "vedant",
        "s",
        [("2026-01-01T00:00:00.000Z", "my fixed deposit", "vedant FD chat")],
    )
    result = handle_recall_conversation({"query": "fixed deposit"}, "mom")
    assert "mom FD chat" in result.content
    assert "vedant FD chat" not in result.content


def test_recall_no_match_is_ok_and_empty(tmp_memory):
    sessions_dir = settings.resolve(settings.sessions_dir)
    _write_turns(sessions_dir, "vedant", "s", [("2026-01-01T00:00:00.000Z", "hello", "hi")])
    result = handle_recall_conversation({"query": "cryptocurrency"}, "vedant")
    assert result.ok  # a search that finds nothing is not an error
    assert "no past conversations" in result.content.lower()


def test_recall_empty_query_is_error(tmp_memory):
    result = handle_recall_conversation({"query": "   "}, "vedant")
    assert not result.ok


def test_recall_caps_number_of_excerpts(tmp_memory):
    sessions_dir = settings.resolve(settings.sessions_dir)
    turns = [
        (f"2026-03-{i:02d}T10:00:00.000Z", "tax saving elss", f"answer {i}")
        for i in range(1, 13)
    ]
    _write_turns(sessions_dir, "vedant", "s", turns)
    result = handle_recall_conversation({"query": "tax saving"}, "vedant")
    # Output is bounded so it never blows the token budget.
    assert result.content.lower().count("you:") <= 6


def test_dispatch_routes_recall_conversation(tmp_memory):
    sessions_dir = settings.resolve(settings.sessions_dir)
    _write_turns(
        sessions_dir,
        "vedant",
        "s",
        [("2026-01-01T00:00:00.000Z", "retirement corpus", "lets plan it")],
    )
    result = default_dispatch().execute(
        "recall_conversation", {"query": "retirement"}, active_member="vedant"
    )
    assert result.ok
    assert "retirement corpus" in result.content
