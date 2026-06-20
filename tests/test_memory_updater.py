from __future__ import annotations

import pytest

from backend.agent import memory_updater
from backend.agent.memory_updater import close_session
from backend.agent.transcripts import is_post_processed, mark_post_processed, transcript_path


@pytest.fixture(autouse=True)
def reset_provider():
    memory_updater._provider = None
    yield
    memory_updater._provider = None


def _write_transcript(member: str, session_id: str) -> None:
    path = transcript_path(member, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"ts":"2026-06-06T10:00:00.000Z","user_msg":"where to park 5L","assistant_msg":"liquid fund"}\n'
    )


def test_financial_cadence_excludes_one_time():
    # One-off items must not be filable as recurring cash flow, so the financial
    # cadence enum offers only recurring options (forcing function for routing
    # one-offs to life_events instead — they'd otherwise sit in finances forever).
    cadence_enum = memory_updater._SUMMARIZE_TOOL["input_schema"]["properties"][
        "financial_fact_updates"]["items"]["properties"]["cadence"]["enum"]
    assert "one_time" not in cadence_enum
    assert "monthly" in cadence_enum and "annual" in cadence_enum


def test_prompt_routes_one_off_to_life_events():
    sys = memory_updater._SUMMARIZER_SYSTEM.lower()
    assert "one-off" in sys  # the explicit routing rule for purchases/trips/windfalls


def test_summarizer_prompt_demands_tool_call():
    # Model-level mitigation of the silent-loss watch-point: with tool_choice
    # "auto" (thinking on) the model could reply in text and skip the tool, so
    # the prompt must explicitly require always calling it. Guarding the phrase
    # against accidental deletion (the code-level None guard is the backstop).
    sys = memory_updater._SUMMARIZER_SYSTEM.lower()
    assert "always call the `summarize` tool" in sys


async def test_member_notes_reach_extractor(tmp_memory, fake_provider):
    # The narrative onboarding note must reach the extractor too, not just the
    # live agent — otherwise extraction repeats mistakes the note would prevent
    # (e.g. mislabeling an f&f settlement as a joining bonus).
    from backend.agent.writers import write_note

    write_note(
        "vedant",
        note="my 61k was the f&f from oracle; joining bonus is ~1L separately",
        date="2026-06-19",
        dedup_id="noteid",
    )
    fake_provider.payload = {"summary_3_lines": ["hi"]}
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "noteseen")

    await close_session("vedant", "noteseen")

    system_text = "\n".join(b.text for b in fake_provider.last_kwargs["system"])
    assert "f&f from oracle" in system_text


async def test_happy_path_writes_summary_and_recommendation(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["talked surplus", "park 5L", "liquid fund"],
        "new_recommendations": [
            {"title": "Park surplus", "priority": 1, "assumptions": "5L matured"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "sess1")

    await close_session("vedant", "sess1")

    conv = (tmp_memory / "members" / "vedant" / "conversations.md").read_text()
    rec = (tmp_memory / "members" / "vedant" / "recommendations.md").read_text()
    assert "park 5L" in conv
    assert "Status: PROPOSED" in rec
    assert is_post_processed("vedant", "sess1")
    assert fake_provider.calls == 1


async def test_already_processed_is_noop(tmp_memory, fake_provider):
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "sess1")
    # Pre-stamp the completion event in the transcript.
    mark_post_processed("vedant", "sess1")

    await close_session("vedant", "sess1")

    # No model call, no files written.
    assert fake_provider.calls == 0
    assert not (tmp_memory / "members" / "vedant" / "conversations.md").exists()


async def test_no_transcript_is_noop(tmp_memory, fake_provider):
    memory_updater._provider = fake_provider
    # No transcript file written for this session.
    await close_session("vedant", "ghost")

    # Nothing to summarize → no model call, no status written, no phantom file.
    assert fake_provider.calls == 0
    assert not is_post_processed("vedant", "ghost")
    assert not transcript_path("vedant", "ghost").exists()


async def test_empty_response_completes_without_entries(tmp_memory, fake_provider):
    fake_provider.payload = {}
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "sess2")

    await close_session("vedant", "sess2")

    # Empty extraction is a clean run → completed, but no entity files created.
    assert is_post_processed("vedant", "sess2")
    assert not (tmp_memory / "members" / "vedant" / "conversations.md").exists()
    assert not (tmp_memory / "members" / "vedant" / "recommendations.md").exists()


async def test_second_close_adds_no_duplicate(tmp_memory, fake_provider):
    fake_provider.payload = {"summary_3_lines": ["one", "two", "three"]}
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "sess3")

    await close_session("vedant", "sess3")
    await close_session("vedant", "sess3")  # already processed → no-op

    conv = (tmp_memory / "members" / "vedant" / "conversations.md").read_text()
    assert conv.count("## ") == 1  # exactly one dated block
    assert fake_provider.calls == 1


# ---------------------------------------------------------------------------
# Two-stage reconcile — new current-value / inference / cross-member routing
# ---------------------------------------------------------------------------

async def test_financial_fact_routed_to_finances(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["raise"],
        "financial_fact_updates": [
            {"category": "income", "label": "salary", "value": "140000",
             "cadence": "monthly", "basis": "got a raise"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "f1")

    await close_session("vedant", "f1")

    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "## income.salary" in fin
    assert "- value: 140000" in fin
    assert "- source: conversation" in fin
    assert is_post_processed("vedant", "f1")


async def test_goal_set_writes_active(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["goal"],
        "goal_updates": [
            {"title": "House", "action": "set", "target": "60L", "horizon": "7y", "basis": "wants house"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "g1")

    await close_session("vedant", "g1")

    goals = (tmp_memory / "members" / "vedant" / "goals.md").read_text()
    assert "## House" in goals
    assert "- lifecycle: ACTIVE" in goals
    assert "- target: 60L" in goals


async def test_goal_complete_writes_agent_notes_pointer(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["done"],
        "goal_updates": [{"title": "Emergency fund", "action": "complete", "basis": "fully funded"}],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "g2")

    await close_session("vedant", "g2")

    goals = (tmp_memory / "members" / "vedant" / "goals.md").read_text()
    notes = (tmp_memory / "members" / "vedant" / "agent_notes.md").read_text()
    assert "- lifecycle: ACHIEVED" in goals
    assert "Emergency fund" in notes
    assert "ACHIEVED" in notes


async def test_goal_set_without_target_is_skipped(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["vague"],
        "goal_updates": [{"title": "Something", "action": "set", "basis": "vague"}],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "g3")

    await close_session("vedant", "g3")

    # Blank-target set is dropped (not written), but the session still completes.
    assert not (tmp_memory / "members" / "vedant" / "goals.md").exists()
    assert is_post_processed("vedant", "g3")


async def test_behavior_inference_routed_to_inferences(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["anxious"],
        "inferences": [
            {"topic": "loss_aversion", "kind": "behavior", "claim": "dislikes drawdowns",
             "basis": "panicked at a dip", "confidence": "med"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "i1")

    await close_session("vedant", "i1")

    inf = (tmp_memory / "members" / "vedant" / "inferences.md").read_text()
    assert "## loss_aversion" in inf
    assert "- claim: dislikes drawdowns" in inf


async def test_risk_inference_routed_to_risk_profile(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["risk"],
        "inferences": [
            {"topic": "risk_tolerance", "kind": "risk", "claim": "moderate",
             "basis": "held through a dip", "confidence": "low"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "i2")

    await close_session("vedant", "i2")

    rp = (tmp_memory / "members" / "vedant" / "risk_profile.md").read_text()
    assert "## risk_tolerance" in rp
    assert "- stance: moderate" in rp


async def test_cross_member_observation_staged_not_cross_written(tmp_memory, fake_provider):
    fake_provider.payload = {
        "summary_3_lines": ["dad"],
        "cross_member_observations": [
            {"observation": "retiring next year", "about": "dad", "basis": "said so"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "x1")

    await close_session("vedant", "x1")

    obs = (tmp_memory / "working" / "cross_member_observations.md").read_text()
    assert "retiring next year" in obs
    assert "dad" in obs
    # never written into another member's tree
    assert not (tmp_memory / "members" / "mom" / "finances.md").exists()


async def test_cross_member_observation_promotes_new_person_to_roster(tmp_memory, fake_provider):
    # M5/#7: an observation about a not-yet-known family member should, after the
    # session closes, land that person in the always-loaded household roster.
    fake_provider.payload = {
        "summary_3_lines": ["bro"],
        "cross_member_observations": [
            {"observation": "18 years old, a student", "about": "brother", "basis": "said so"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "p1")

    await close_session("vedant", "p1")

    hh = (tmp_memory / "family" / "household.md").read_text()
    assert "| brother |" in hh           # promoted into the roster
    assert "| brother | brother | brother | no |" in hh   # student -> not earning
    assert is_post_processed("vedant", "p1")


async def test_lower_authority_financial_stages_but_session_completes(tmp_memory, fake_provider):
    from backend.agent.writers import write_financial_fact

    # A verified upload value exists; a conversational guess conflicts.
    write_financial_fact(
        "vedant", key="income.salary", value="200000", category="income", cadence="monthly",
        source="document_upload", confidence="high", as_of="2026-06-01", dedup_id="seed",
    )
    fake_provider.payload = {
        "summary_3_lines": ["maybe"],
        "financial_fact_updates": [
            {"category": "income", "label": "salary", "value": "150000",
             "cadence": "monthly", "basis": "thinks ~1.5L"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "s1")

    await close_session("vedant", "s1")

    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "- value: 200000" in fin  # upload value untouched
    assert "- value: 150000" not in fin
    disc = (tmp_memory / "working" / "discrepancies.md").read_text()
    assert "income.salary" in disc
    # STAGED is a clean dispatch → the session still post-processes.
    assert is_post_processed("vedant", "s1")


async def test_api_error_does_not_complete_and_is_retriable(tmp_memory, fake_provider):
    # complete_json returns None when the model call FAILS (vs {} for a genuine
    # empty extraction). A failure must NOT be mistaken for a clean empty run:
    # the session stays un-stamped so the catch-up scan retries it, instead of
    # being marked done with its memory silently lost.
    fake_provider.payload = None
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "err1")

    await close_session("vedant", "err1")

    assert not is_post_processed("vedant", "err1")  # retriable, not silently lost
    assert not (tmp_memory / "members" / "vedant" / "conversations.md").exists()


async def test_financial_edit_targets_existing_block_no_duplicate(tmp_memory, fake_provider):
    # M4: extractor reports the same expense under a different label but TARGETS
    # the existing block's id → the update lands on that block's key, not a
    # parallel one. Closes #2 (duplicate fact, two keys) / #6 (key drift).
    from backend.agent.writers import write_financial_fact

    write_financial_fact(
        "vedant", key="expense.total", value="25000", category="expense",
        cadence="monthly", source="conversation", confidence="low",
        as_of="2026-06-01", dedup_id="exp1",
    )
    fake_provider.payload = {
        "summary_3_lines": ["spend"],
        "financial_fact_updates": [
            {"category": "expense", "label": "personal spending", "value": "30000",
             "cadence": "monthly", "basis": "spends 30k now", "target_id": "exp1"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "m4a")

    await close_session("vedant", "m4a")

    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "## expense.personal spending" not in fin   # NO parallel key
    assert "- value: 30000" in fin                      # new current value
    assert "- status: SUPERSEDED" in fin                # old one kept, superseded
    assert fin.count("## expense.total") == 2           # superseded + current


async def test_bad_target_id_appends_as_new_block(tmp_memory, fake_provider):
    # Decision (2026-06-15): a hallucinated/unknown target_id falls back to the
    # candidate's own key — appended as a new block, not dropped or crashed.
    from backend.agent.writers import write_financial_fact

    write_financial_fact(
        "vedant", key="expense.total", value="25000", category="expense",
        cadence="monthly", source="conversation", confidence="low",
        as_of="2026-06-01", dedup_id="exp1",
    )
    fake_provider.payload = {
        "summary_3_lines": ["spend"],
        "financial_fact_updates": [
            {"category": "expense", "label": "gym", "value": "2000",
             "cadence": "monthly", "basis": "new gym fee", "target_id": "ghost"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "m4b")

    await close_session("vedant", "m4b")

    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "## expense.gym" in fin       # appended under its own key
    assert "- value: 2000" in fin
    assert is_post_processed("vedant", "m4b")


async def test_targeted_edit_lower_authority_stages_no_duplicate(tmp_memory, fake_provider):
    # Targeting a higher-authority block with a low-authority value must NOT
    # clobber it and must NOT spawn a parallel key — it stages a discrepancy.
    from backend.agent.writers import write_financial_fact

    write_financial_fact(
        "vedant", key="expense.total", value="25000", category="expense",
        cadence="monthly", source="document_upload", confidence="high",
        as_of="2026-06-01", dedup_id="exp1",
    )
    fake_provider.payload = {
        "summary_3_lines": ["spend"],
        "financial_fact_updates": [
            {"category": "expense", "label": "personal spending", "value": "99999",
             "cadence": "monthly", "basis": "thinks ~99999", "target_id": "exp1"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "m4c")

    await close_session("vedant", "m4c")

    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "- value: 25000" in fin                     # upload value untouched
    assert "- value: 99999" not in fin
    assert "## expense.personal spending" not in fin    # no parallel key
    disc = (tmp_memory / "working" / "discrepancies.md").read_text()
    assert "expense.total" in disc
    assert is_post_processed("vedant", "m4c")


async def test_existing_memory_is_fed_to_extractor_with_ids(tmp_memory, fake_provider):
    # M3 de-blind: the member's current-value files (with id markers) must reach
    # the extractor so it can see what already exists. The id markers MUST survive
    # frontmatter stripping (the M4 edit-ops will target them).
    from backend.agent.writers import write_financial_fact

    write_financial_fact(
        "vedant", key="income.salary", value="120000", category="income",
        cadence="monthly", source="onboarding_form", confidence="high",
        as_of="2026-06-01", dedup_id="seedid",
    )
    fake_provider.payload = {"summary_3_lines": ["hi"]}
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "m3a")

    await close_session("vedant", "m3a")

    system_text = "\n".join(b.text for b in fake_provider.last_kwargs["system"])
    assert "income.salary" in system_text       # existing fact is visible
    assert "120000" in system_text
    assert "<!-- id:seedid -->" in system_text   # WATCH-POINT: ids survive stripping


async def test_close_session_without_existing_memory_still_runs(tmp_memory, fake_provider):
    # No member files yet (first ever session) → extractor just gets the prompt,
    # no crash, session completes.
    fake_provider.payload = {"summary_3_lines": ["hi"]}
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "m3b")

    await close_session("vedant", "m3b")

    assert fake_provider.calls == 1
    assert is_post_processed("vedant", "m3b")


async def test_asset_update_routed_to_portfolio_summary(tmp_memory, fake_provider):
    # An asset the member states in conversation is captured into the asset
    # register (portfolio_summary), conversation-sourced + low confidence.
    fake_provider.payload = {
        "summary_3_lines": ["assets"],
        "asset_updates": [
            {"asset_class": "cash", "label": "emergency_fund", "value": "30000",
             "basis": "have about 30k as an emergency fund"}
        ],
    }
    memory_updater._provider = fake_provider
    _write_transcript("vedant", "asset1")

    await close_session("vedant", "asset1")

    ps = (tmp_memory / "members" / "vedant" / "portfolio_summary.md").read_text()
    assert "## cash.emergency_fund" in ps
    assert "- value: 30000" in ps
    assert "- source: conversation" in ps
    assert is_post_processed("vedant", "asset1")
