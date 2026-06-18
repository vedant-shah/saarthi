"""Tool name -> handler dispatch.

`execute` never raises: an unknown tool name or a handler exception comes back
as a readable error string the model can recover from, so one bad tool call
never crashes the turn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    content: str  # the tool_result text handed back to the model
    ok: bool  # False for errors/not-found (recorded in the transcript)


# A handler takes (tool_input, active_member) and returns a ToolResult.
Handler = Callable[[dict, str], ToolResult]


class ToolDispatch:
    def __init__(self, handlers: dict[str, Handler]) -> None:
        self._handlers = dict(handlers)

    def execute(self, name: str, tool_input: dict, *, active_member: str) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            logger.warning("unknown tool requested: %s", name)
            return ToolResult(f"[tool error] unknown tool: {name}", ok=False)
        try:
            return handler(tool_input, active_member)
        except Exception:
            logger.exception("tool handler failed: %s", name)
            return ToolResult(f"[tool error] {name} failed", ok=False)


def default_dispatch() -> ToolDispatch:
    # Imported here, not at module level, to avoid a cycle: the handlers import
    # ToolResult from this module.
    from backend.agent.tools.read_context import handle_read_context
    from backend.agent.tools.recall_conversation import handle_recall_conversation
    from backend.agent.tools.specs import READ_CONTEXT, RECALL_CONVERSATION

    return ToolDispatch(
        {
            READ_CONTEXT: handle_read_context,
            RECALL_CONVERSATION: handle_recall_conversation,
        }
    )
