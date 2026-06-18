"""The Tier 3 agent tool-use loop.

`run_agent_loop` wraps the single-round `run_turn`: when a round ends in a tool
call it executes the tool, feeds the result back, and re-streams — until the
model gives a final (non-tool) answer or the iteration cap is hit. It yields the
same stream events the pipeline already handles, plus a ToolPhaseBoundary marker
so the pipeline can flush the "let me check on that" bubble before the lookup.
"""
from __future__ import annotations

from backend.agent.agent_loop import ToolPhaseBoundary, run_agent_loop
from backend.agent.assembler import AssembledPrompt
from backend.agent.llm_provider import (
    StreamEnd,
    SystemBlock,
    TextDelta,
    ToolUseRequest,
)
from backend.agent.tools.dispatch import ToolDispatch, ToolResult
from tests.conftest import ScriptedProvider


def _prompt(level: str = "FULL") -> AssembledPrompt:
    return AssembledPrompt(
        system=[SystemBlock(text="sys")],
        messages=[{"role": "user", "content": "q"}],
        context_level=level,
        debug={},
    )


def _end(reason: str) -> StreamEnd:
    return StreamEnd(
        stop_reason=reason,
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def _stub_dispatch(content: str = "PLAYBOOK", ok: bool = True) -> ToolDispatch:
    return ToolDispatch({"read_context": lambda inp, member: ToolResult(content, ok)})


async def _run(provider, dispatch, *, max_iterations=4, log=None):
    log = [] if log is None else log
    events = [
        ev
        async for ev in run_agent_loop(
            provider=provider,
            prompt=_prompt(),
            dispatch=dispatch,
            active_member="vedant",
            max_tokens=100,
            max_iterations=max_iterations,
            tool_calls_log=log,
        )
    ]
    return events, log


async def test_single_round_no_tools_passes_through():
    provider = ScriptedProvider([[TextDelta("hey whats up"), _end("end_turn")]])
    events, log = await _run(provider, _stub_dispatch())

    assert len(provider.calls) == 1  # exactly one model round-trip
    assert [type(e).__name__ for e in events] == ["TextDelta", "StreamEnd"]
    assert not any(isinstance(e, ToolPhaseBoundary) for e in events)
    assert log == []


async def test_tool_use_round_then_final_text():
    provider = ScriptedProvider(
        [
            [
                TextDelta("let me check on that"),
                ToolUseRequest(
                    tool_use_id="tu_1",
                    name="read_context",
                    input={"name": "skill.surplus_allocation"},
                ),
                _end("tool_use"),
            ],
            [TextDelta("here's the answer"), _end("end_turn")],
        ]
    )
    events, log = await _run(provider, _stub_dispatch("PLAYBOOK"))

    # Two round-trips: the model was re-invoked after the tool ran.
    assert len(provider.calls) == 2

    # The second call carries the tool_result appended after the assistant turn.
    second_msgs = provider.calls[1]["messages"]
    assistant_turn = second_msgs[-2]
    tool_result_turn = second_msgs[-1]
    assert assistant_turn["role"] == "assistant"
    assert any(
        b["type"] == "tool_use" and b["id"] == "tu_1" for b in assistant_turn["content"]
    )
    assert tool_result_turn["role"] == "user"
    block = tool_result_turn["content"][0]
    assert block["type"] == "tool_result"
    assert block["tool_use_id"] == "tu_1"
    assert block["content"] == "PLAYBOOK"

    # Event order: pre-tool text, boundary (flush point), post-tool text, end.
    assert [type(e).__name__ for e in events] == [
        "TextDelta",
        "ToolPhaseBoundary",
        "TextDelta",
        "StreamEnd",
    ]
    assert events[0].text == "let me check on that"
    assert events[1].tool_names == ("read_context",)
    assert events[2].text == "here's the answer"

    # The tool call is recorded for the transcript.
    assert log == [
        {"name": "read_context", "input": {"name": "skill.surplus_allocation"}, "ok": True}
    ]


async def test_max_iterations_synthesizes_terminal_stream_end():
    def tool_round():
        return [
            TextDelta("checking"),
            ToolUseRequest(
                tool_use_id="tu",
                name="read_context",
                input={"name": "skill.surplus_allocation"},
            ),
            _end("tool_use"),
        ]

    provider = ScriptedProvider([tool_round() for _ in range(5)])
    events, _ = await _run(provider, _stub_dispatch(), max_iterations=2)

    assert len(provider.calls) == 2  # capped, did not run forever
    assert isinstance(events[-1], StreamEnd)
    assert events[-1].stop_reason == "max_tool_iterations"


async def test_tools_offered_even_on_minimal_turns():
    # Tools ride along on every turn, including MINIMAL — so meta/history
    # questions that carry no financial content (and classify MINIMAL) can still
    # reach recall. A plain greeting simply won't call them.
    provider = ScriptedProvider([[TextDelta("hey"), _end("end_turn")]])
    log = []
    [
        ev
        async for ev in run_agent_loop(
            provider=provider,
            prompt=_prompt("MINIMAL"),
            dispatch=_stub_dispatch(),
            active_member="vedant",
            max_tokens=100,
            max_iterations=4,
            tool_calls_log=log,
        )
    ]
    assert provider.calls[0]["tools"] is not None
