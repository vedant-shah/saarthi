"""
Shared test fixtures.

`asyncio_mode = "auto"` (pyproject) means async tests need no decorator.
No test touches the network or the real `memory/` tree: a FakeProvider stands
in for the model, and `tmp_memory` repoints settings.memory_dir/sessions_dir at
a tmp_path.
"""
from __future__ import annotations

from typing import AsyncIterator

import pytest

from backend.config import settings


class FakeProvider:
    """In-memory stand-in for LLMProvider. `complete_json` returns a canned dict
    and records call count; `stream` is a no-op to satisfy the Protocol."""

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload if payload is not None else {}
        self.calls = 0
        self.last_kwargs: dict | None = None

    async def stream(self, **kwargs) -> AsyncIterator:  # pragma: no cover - unused here
        if False:
            yield None

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        self.last_kwargs = kwargs
        return self.payload


class ScriptedProvider:
    """Streams a pre-scripted sequence of rounds for tool-loop tests. Each call
    to `stream` pops the next round (a list of StreamEvents) and yields it,
    recording the kwargs it was called with so a test can assert what messages
    and tools each round-trip received."""

    def __init__(self, rounds: list[list]) -> None:
        self.rounds = [list(r) for r in rounds]
        self.calls: list[dict] = []

    async def stream(self, **kwargs) -> AsyncIterator:
        self.calls.append(kwargs)
        events = self.rounds.pop(0) if self.rounds else []
        for ev in events:
            yield ev

    async def complete_json(self, **kwargs) -> dict:
        return {}


@pytest.fixture(autouse=True)
def _reset_sessions_state():
    """Clear the sessions module's process-global in-memory state before each
    test. Without this, _active/_activity/_history leak across tests and results
    depend on execution order (a turn can reuse a session another test created)."""
    from backend.agent import sessions

    sessions._active.clear()
    sessions._activity.clear()
    sessions._history.clear()
    yield


@pytest.fixture(autouse=True)
def _disable_mdns(monkeypatch):
    """Never broadcast a Bonjour name during tests. The endpoint tests run the
    app lifespan via TestClient, and real mDNS registration is slow and would
    collide with a running dev server. Production keeps it on by default."""
    monkeypatch.setattr(settings, "mdns_enabled", False)


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def tmp_memory(tmp_path, monkeypatch):
    """Point memory + sessions dirs at tmp_path and create the standard member
    tree (vedant, mom) plus family/. Returns the memory root Path."""
    memory_dir = tmp_path / "memory"
    sessions_dir = tmp_path / "sessions"
    for member in ("vedant", "mom"):
        (memory_dir / "members" / member).mkdir(parents=True)
    (memory_dir / "family").mkdir(parents=True)
    sessions_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "memory_dir", memory_dir)
    monkeypatch.setattr(settings, "sessions_dir", sessions_dir)
    return memory_dir
