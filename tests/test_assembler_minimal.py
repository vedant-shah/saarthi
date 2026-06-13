"""The advisor's texting voice must survive MINIMAL context level.

MINIMAL is chosen for greetings/chit-chat ("hey", "tell me about yourself").
If the persona isn't loaded there, the model falls back to default-assistant
voice (markdown headers, "I'm your personal financial advisor", em dashes) on
exactly the messages where the texting voice matters most. So the MINIMAL
prompt must carry the persona and must NOT use the generic advisor stamp.
"""
from __future__ import annotations

from backend.agent.assembler import assemble
from backend.config import settings

MINIMAL_CLASSIFICATION = {
    "context_level": "MINIMAL",
    "relevant_memory_files": [],
    "is_followup": False,
}


def _minimal_system_text(member: str = "vedant") -> str:
    prompt = assemble(
        active_member=member,
        classifier_output=MINIMAL_CLASSIFICATION,
        in_session_history=[],
        user_message="hey",
        memory_root=settings.resolve(settings.memory_dir),
        skills_root=settings.resolve(settings.skills_dir),
    )
    return "\n\n".join(block.text for block in prompt.system)


def test_minimal_prompt_carries_persona_voice(tmp_memory) -> None:
    text = _minimal_system_text().lower()
    # Distinctive persona rules that only exist in core_system.md
    assert "em dash" in text
    assert "preamble" in text


def test_minimal_prompt_drops_generic_advisor_stamp(tmp_memory) -> None:
    text = _minimal_system_text()
    assert "You are a personal financial advisor" not in text


def test_minimal_prompt_keeps_session_context(tmp_memory) -> None:
    text = _minimal_system_text()
    assert "Today's date" in text
    assert "vedant" in text
