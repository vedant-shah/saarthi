"""Quoted reply (swipe-to-reply): when the user replies to a specific message,
the model must see WHAT they're replying to, attributed by who said it. The
quote rides inline in the user turn (so the model understands the reference);
the raw message stays in history; the transcript records the quote for audit and
better extraction.
"""
from __future__ import annotations

import json
import time

from backend.agent import sessions, transcripts
from backend.agent.llm_provider import StreamEnd, TextDelta
from backend.agent.pipeline import _with_quote, run_chat_turn
from backend.config import settings

_CLASSIFY = {"context_level": "FULL", "intent": "general", "is_followup": True}


class CapturingProvider:
    """complete_json drives the classifier; stream records the messages it was
    handed (so we can assert the quote reached the model) and ends the turn."""

    def __init__(self):
        self.messages = None

    async def complete_json(self, **kwargs):
        return _CLASSIFY

    async def stream(self, **kwargs):
        self.messages = kwargs.get("messages")
        yield TextDelta("got it")
        yield StreamEnd(
            stop_reason="end_turn", input_tokens=1, output_tokens=1,
            cache_read_tokens=0, cache_write_tokens=0,
        )


def test_with_quote_empty_is_passthrough():
    assert _with_quote("hi", None, "") == "hi"
    assert _with_quote("hi", "", "assistant") == "hi"


def test_with_quote_attributes_role():
    adv = _with_quote("its 35k now", "ur emergency fund is 30k", "assistant")
    assert "your earlier message" in adv
    assert "ur emergency fund is 30k" in adv
    assert "its 35k now" in adv

    own = _with_quote("make that 25k", "i'll give mum 15k", "user")
    assert "their own earlier message" in own


async def test_quote_reaches_prompt_but_history_stays_raw(tmp_memory):
    provider = CapturingProvider()
    async for _ in run_chat_turn(
        provider=provider,
        member="vedant",
        user_message="actually its 35k now",
        quoted_text="ur emergency fund is 30k",
        quoted_role="assistant",
        memory_root=tmp_memory,
        skills_root=settings.resolve(settings.skills_dir),
        max_tokens=50,
    ):
        pass

    # The model saw the quote inline in the final user turn.
    last_user = provider.messages[-1]
    assert last_user["role"] == "user"
    assert "ur emergency fund is 30k" in last_user["content"]
    assert "actually its 35k now" in last_user["content"]

    # In-session history keeps the RAW message (no bracket prefix to clutter it).
    sid = sessions.get_active("vedant", time.monotonic())
    users = [m for m in sessions.get_history("vedant", sid) if m["role"] == "user"]
    assert users[-1]["content"] == "actually its 35k now"

    # The transcript records the quote for audit + extraction.
    path = transcripts.transcript_path("vedant", sid)
    lines = [json.loads(line) for line in path.read_text().splitlines() if '"turn_id"' in line]
    assert lines[-1]["quoted_text"] == "ur emergency fund is 30k"
    assert lines[-1]["quoted_role"] == "assistant"
