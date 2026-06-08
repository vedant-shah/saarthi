from __future__ import annotations

from backend.agent.classifier import classify


async def test_empty_response_falls_back(fake_provider):
    fake_provider.payload = {}
    result = await classify(
        provider=fake_provider,
        member="vedant",
        user_message="where should I park 5 lakh that just matured?",
        history=[],
    )
    assert result.intent == "portfolio_review"
    assert result.output["context_level"] == "FULL"
    assert result.output["is_followup"] is False


async def test_valid_response_maps_files(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "surplus_allocation",
        "is_followup": False,
    }
    result = await classify(
        provider=fake_provider,
        member="vedant",
        user_message="where should I park 5 lakh that just matured?",
        history=[],
    )
    assert result.intent == "surplus_allocation"
    assert result.output["relevant_memory_files"] == [
        "members/vedant/goals",
        "members/vedant/portfolio_summary",
        "members/vedant/finances",
    ]


async def test_minimal_loads_no_files(fake_provider):
    fake_provider.payload = {
        "context_level": "MINIMAL",
        "intent": "general",
        "is_followup": False,
    }
    result = await classify(
        provider=fake_provider,
        member="vedant",
        user_message="hi",
        history=[],
    )
    assert result.output["context_level"] == "MINIMAL"
    assert result.output["relevant_memory_files"] == []


async def test_unknown_intent_falls_back(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "made_up_intent",
        "is_followup": True,
    }
    result = await classify(
        provider=fake_provider,
        member="vedant",
        user_message="and what about tax?",
        history=[],
    )
    assert result.intent == "portfolio_review"
    assert result.output["is_followup"] is False


async def test_recent_history_is_sent_to_the_model(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "debt_management",
        "is_followup": True,
    }
    history = [
        {"role": "user", "content": "where should I park 5 lakh?"},
        {"role": "assistant", "content": "what's your emergency fund like?"},
    ]
    await classify(
        provider=fake_provider,
        member="vedant",
        user_message="and my home loan?",
        history=history,
    )
    sent = fake_provider.last_kwargs["messages"][0]["content"]
    assert "Recent conversation" in sent
    assert "where should I park 5 lakh?" in sent
    assert "advisor: what's your emergency fund like?" in sent
    assert "Message to classify:\nand my home loan?" in sent


async def test_no_history_omits_context_block(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "surplus_allocation",
        "is_followup": False,
    }
    await classify(
        provider=fake_provider,
        member="vedant",
        user_message="where do I park 5L?",
        history=[],
    )
    sent = fake_provider.last_kwargs["messages"][0]["content"]
    assert "Recent conversation" not in sent
    assert sent == "Message to classify:\nwhere do I park 5L?"


async def test_each_turn_invokes_the_model(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "surplus_allocation",
        "is_followup": False,
    }
    await classify(
        provider=fake_provider, member="vedant", user_message="where do I park 5L?", history=[]
    )
    await classify(
        provider=fake_provider, member="vedant", user_message="why?", history=[]
    )
    # No caching anymore — every turn re-classifies.
    assert fake_provider.calls == 2


async def test_history_truncated_to_recent_messages(fake_provider):
    fake_provider.payload = {
        "context_level": "FULL",
        "intent": "general",
        "is_followup": False,
    }
    history = [{"role": "user", "content": f"old message {i}"} for i in range(10)]
    await classify(
        provider=fake_provider,
        member="vedant",
        user_message="latest?",
        history=history,
    )
    sent = fake_provider.last_kwargs["messages"][0]["content"]
    assert "old message 9" in sent  # recent kept
    assert "old message 0" not in sent  # oldest dropped
