"""Tier 3 agent tool-use loop.

`run_turn` is one model round-trip. This loop wraps it: forward the model's
text, and when a round ends asking for a tool, run the tool, append the result,
and re-stream — until the model answers without a tool or the iteration cap is
hit.

It yields the same StreamEvents the pipeline already handles (TextDelta /
StreamError / a single terminal StreamEnd), plus a ToolPhaseBoundary marker
emitted after a tool-use round's text but BEFORE the tool runs — so the pipeline
can flush the "let me check on that" bubble to the user during the lookup.

`prompt.messages` is never mutated; each round rebuilds a local message list.
"""
from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from backend.agent.assembler import AssembledPrompt
from backend.agent.llm_provider import (
    LLMProvider,
    StreamEnd,
    StreamError,
    TextDelta,
    ToolUseRequest,
)
from backend.agent.orchestrator import run_turn
from backend.agent.tools.dispatch import ToolDispatch
from backend.agent.tools.specs import tool_specs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolPhaseBoundary:
    """Yielded after a tool-use round's text but before the tool runs, so the
    pipeline can flush the pre-tool bubble to the user during the lookup."""

    tool_names: tuple[str, ...]


LoopEvent = TextDelta | StreamError | StreamEnd | ToolPhaseBoundary


def _assistant_turn(text_parts: list[str], tools: list[ToolUseRequest]) -> dict:
    """Rebuild the assistant turn (text + tool_use blocks) to send back so the
    follow-up tool_result lines up with the tool_use ids."""
    blocks: list[dict] = []
    text = "".join(text_parts).strip()
    if text:
        blocks.append({"type": "text", "text": text})
    for t in tools:
        blocks.append(
            {"type": "tool_use", "id": t.tool_use_id, "name": t.name, "input": t.input}
        )
    return {"role": "assistant", "content": blocks}


async def run_agent_loop(
    *,
    provider: LLMProvider,
    prompt: AssembledPrompt,
    dispatch: ToolDispatch,
    active_member: str,
    max_tokens: int,
    max_iterations: int,
    tool_calls_log: list[dict],
) -> AsyncIterator[LoopEvent]:
    # Tools ride along on every turn, including MINIMAL. Meta/history questions
    # ("what did we first talk about") carry no financial content and classify
    # MINIMAL, but still need recall — so we never gate tools by level. The model
    # only calls a tool when it needs one; a plain greeting won't.
    specs = tool_specs()
    working_messages = list(prompt.messages)

    for _iteration in range(max_iterations):
        round_text: list[str] = []
        round_tools: list[ToolUseRequest] = []
        last_end: StreamEnd | None = None

        round_prompt = dataclasses.replace(prompt, messages=working_messages)
        async for ev in run_turn(
            provider=provider, prompt=round_prompt, tools=specs, max_tokens=max_tokens
        ):
            if isinstance(ev, TextDelta):
                round_text.append(ev.text)
                yield ev
            elif isinstance(ev, ToolUseRequest):
                round_tools.append(ev)  # absorbed; never forwarded to the pipeline
            elif isinstance(ev, StreamError):
                yield ev
                return
            elif isinstance(ev, StreamEnd):
                last_end = ev

        # Terminal round: the model answered without (or instead of) a tool call.
        if last_end is None or last_end.stop_reason != "tool_use" or not round_tools:
            if last_end is not None:
                yield last_end
            return

        # Flush the pre-tool text to the user, THEN execute the tools.
        yield ToolPhaseBoundary(tool_names=tuple(t.name for t in round_tools))

        result_blocks: list[dict] = []
        for req in round_tools:
            result = dispatch.execute(req.name, req.input, active_member=active_member)
            tool_calls_log.append(
                {"name": req.name, "input": req.input, "ok": result.ok}
            )
            result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": req.tool_use_id,
                    "content": result.content,
                }
            )

        working_messages = working_messages + [
            _assistant_turn(round_text, round_tools),
            {"role": "user", "content": result_blocks},
        ]

    # Hit the iteration cap: synthesize a terminal StreamEnd so the pipeline
    # still finalizes the turn (history + transcript + TurnDone) rather than
    # hanging or losing the partial reply.
    logger.warning("agent loop hit max_iterations=%d", max_iterations)
    yield StreamEnd(
        stop_reason="max_tool_iterations",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )
