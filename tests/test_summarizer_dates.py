"""Relative time in conversations must become absolute dates during extraction.

The summarizer is told the conversation's actual date (from the transcript's
timestamps, not the processing date, which can be days later) and instructed to
convert every relative reference (yesterday/today/last week) to YYYY-MM-DD. So a
fact stated as "bought it yesterday" never lands in memory as "yesterday".
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.agent import memory_updater, transcripts


@pytest.fixture(autouse=True)
def _reset_provider():
    memory_updater._provider = None
    yield
    memory_updater._provider = None


def test_conversation_date_from_first_timestamp():
    content = (
        '{"ts":"2026-06-19T10:00:00.000Z","turn_id":"t01","user_msg":"hi","assistant_msg":"yo"}\n'
        '{"ts":"2026-06-19T10:05:00.000Z","turn_id":"t02","user_msg":"more","assistant_msg":"ok"}\n'
    )
    assert memory_updater._conversation_date(content) == "2026-06-19"


def test_conversation_date_fallback_when_no_ts():
    assert memory_updater._conversation_date("not json\n") == date.today().isoformat()


async def test_close_session_tells_summarizer_the_conversation_date(tmp_memory, fake_provider):
    p = transcripts.transcript_path("vedant", "s1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"ts":"2026-06-19T10:00:00.000Z","turn_id":"t01",'
        '"user_msg":"i bought the watch yesterday","assistant_msg":"nice"}\n'
    )
    fake_provider.payload = {"summary_3_lines": ["bought a watch"]}
    memory_updater._provider = fake_provider

    await memory_updater.close_session("vedant", "s1")

    system_text = "\n\n".join(b.text for b in fake_provider.last_kwargs["system"])
    assert "2026-06-19" in system_text  # the conversation date is given to the summarizer
    assert "yesterday" in system_text.lower()  # alongside the convert-relative-time rule
