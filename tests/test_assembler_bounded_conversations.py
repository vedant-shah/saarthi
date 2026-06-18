"""Tier 1 preloads only the most recent conversation summaries.

`conversations.md` grows one dated block per session forever. Loading the whole
file into every prompt would blow the Tier 1 budget at scale, so the assembler
keeps only the last `preloaded_summary_count` blocks. Older summaries stay on
disk and are reachable on demand via recall_conversation.
"""
from __future__ import annotations

import pytest

from backend.agent.assembler import assemble
from backend.config import settings

_FULL = {"context_level": "FULL", "relevant_memory_files": [], "is_followup": False}


@pytest.fixture
def root_with_conversations(tmp_path, monkeypatch):
    (tmp_path / "skills").mkdir()
    persona = (settings.project_root / "skills" / "core_system.md").read_text()
    (tmp_path / "skills" / "core_system.md").write_text(persona)

    mem = tmp_path / "memory"
    (mem / "family").mkdir(parents=True)
    d = mem / "members" / "vedant"
    d.mkdir(parents=True)
    (mem / "family" / "household.md").write_text(
        "---\nlast_updated: 2026-06-14\n---\n# Household\n- vedant self\n"
    )
    (d / "profile.md").write_text("## identity.name\n- name: vedant\n- status: CURRENT\n")
    # Eight dated session-summary blocks, oldest (topic 1) to newest (topic 8).
    blocks = "".join(f"\n## 2026-0{i}-01\n- talked about topic {i}\n" for i in range(1, 9))
    (d / "conversations.md").write_text(f"---\nlast_updated: 2026-08-01\n---\n{blocks}")

    monkeypatch.setattr(settings, "project_root", tmp_path)
    monkeypatch.setattr(settings, "memory_dir", mem)
    return mem


def _full_text(mem) -> str:
    prompt = assemble(
        active_member="vedant",
        classifier_output=_FULL,
        in_session_history=[],
        user_message="hi",
        memory_root=mem,
        skills_root=settings.resolve(settings.skills_dir),
    )
    return "\n\n".join(b.text for b in prompt.system)


def test_only_last_n_conversation_blocks_preloaded(root_with_conversations, monkeypatch):
    monkeypatch.setattr(settings, "preloaded_summary_count", 5)
    text = _full_text(root_with_conversations)
    # The newest five (topics 4-8) survive; the older three are dropped.
    assert "topic 8" in text
    assert "topic 4" in text
    assert "topic 3" not in text
    assert "topic 1" not in text


def test_fewer_blocks_than_cap_keeps_all(root_with_conversations, monkeypatch):
    monkeypatch.setattr(settings, "preloaded_summary_count", 20)
    text = _full_text(root_with_conversations)
    assert "topic 1" in text
    assert "topic 8" in text
