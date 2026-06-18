"""Tool schemas advertised to the main agent.

The `read_context` name-enum is generated from the registry's agent-invokable
entries, so the model can only ever name a real on-demand file — never a Tier 1
file or an arbitrary path. This is the first of the scope guards.
"""
from __future__ import annotations

from backend.agent.context_registry import entries_by_policy

READ_CONTEXT = "read_context"
RECALL_CONVERSATION = "recall_conversation"


def _agent_invoked_names() -> list[str]:
    return [e.name for e in entries_by_policy("agent_invoked")]


def tool_specs() -> list[dict]:
    return [
        {
            "name": READ_CONTEXT,
            "description": (
                "Load one on-demand context file by name: a skill playbook or a "
                "memory file you need but that wasn't already in your context. "
                "Returns the file's text, or a short error if it can't be read. "
                "Only call this when you actually need data you don't already have."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": _agent_invoked_names(),
                        "description": "Registry name of the context to load.",
                    }
                },
                "required": ["name"],
            },
        },
        {
            "name": RECALL_CONVERSATION,
            "description": (
                "Keyword-search this person's OLDER conversations, further back "
                "than the recent summaries already in your context. Returns dated "
                "excerpts of the best-matching past turns. Use when they refer to "
                "something you discussed a while ago that you don't already have."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search past conversations for.",
                    }
                },
                "required": ["query"],
            },
        },
    ]
