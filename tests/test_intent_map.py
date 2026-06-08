from __future__ import annotations

from backend.agent.intent_map import INTENT_FILES, files_for_intent


def test_surplus_allocation_resolves_three_stems():
    assert files_for_intent("surplus_allocation", "vedant") == [
        "members/vedant/goals",
        "members/vedant/portfolio_summary",
        "members/vedant/finances",
    ]


def test_every_intent_key_resolves_without_error():
    for intent in INTENT_FILES:
        stems = files_for_intent(intent, "vedant")
        assert isinstance(stems, list)


def test_stems_have_no_prefix_or_suffix_and_substitute_member():
    for intent in INTENT_FILES:
        for stem in files_for_intent(intent, "vedant"):
            assert not stem.startswith("memory/")
            assert not stem.endswith(".md")
            assert "{member}" not in stem
            assert "/vedant/" in stem


def test_unknown_intent_returns_empty():
    assert files_for_intent("nonsense", "vedant") == []


def test_empty_intent_buckets_return_empty():
    assert files_for_intent("life_event", "vedant") == []
    assert files_for_intent("general", "vedant") == []
