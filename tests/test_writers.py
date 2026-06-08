from __future__ import annotations

import pytest

from backend.agent import writers
from backend.agent.current_value import UpsertOutcome
from backend.agent.writers import CrossMemberWriteError
from backend.config import settings


def test_own_recommendation_written_with_schema_fields(tmp_memory):
    writers.write_recommendation(
        "vedant", title="Park surplus", priority=1, body="5L FD matured", date="2026-06-01"
    )
    content = (tmp_memory / "members" / "vedant" / "recommendations.md").read_text()
    assert "## Park surplus" in content
    assert "Date: 2026-06-01" in content
    assert "Priority: P1" in content
    assert "Status: PROPOSED" in content
    assert "Assumptions_at_time: 5L FD matured" in content


def test_conversation_summary_appends_dated_block(tmp_memory):
    writers.append_conversation_summary(
        "vedant", date="2026-06-01", summary_lines=["talked surplus", "park 5L liquid"]
    )
    content = (tmp_memory / "members" / "vedant" / "conversations.md").read_text()
    assert "## 2026-06-01" in content
    assert "- talked surplus" in content
    assert "- park 5L liquid" in content


def test_goal_and_life_event_write_to_own_tree(tmp_memory):
    writers.write_goal("vedant", title="House", target="50L", horizon="7y", date="2026-06-01")
    writers.write_life_event("vedant", description="got married", date="2026-06-01")
    assert (tmp_memory / "members" / "vedant" / "goals.md").exists()
    assert (tmp_memory / "members" / "vedant" / "life_events.md").exists()


def test_cross_member_write_raises(tmp_memory):
    other = settings.resolve(settings.memory_dir) / "members" / "mom" / "recommendations.md"
    with pytest.raises(CrossMemberWriteError):
        writers._assert_writable("vedant", other)


def test_cross_member_via_public_writer_raises(tmp_memory, monkeypatch):
    # Force _member_file to resolve to another member's path, simulating a
    # hallucinated target, and confirm the guard catches it.
    bad = settings.resolve(settings.memory_dir) / "members" / "mom" / "recommendations.md"
    monkeypatch.setattr(writers, "_member_file", lambda writer, fname: bad)
    with pytest.raises(CrossMemberWriteError):
        writers.write_recommendation(
            "vedant", title="x", priority=2, body="y", date="2026-06-01"
        )


def test_family_write_allowed(tmp_memory):
    family_file = settings.resolve(settings.memory_dir) / "family" / "inferences.md"
    # Should not raise — family/ is a permitted destination for any writer.
    writers._assert_writable("vedant", family_file)


def test_working_write_allowed(tmp_memory):
    working_file = settings.resolve(settings.memory_dir) / "working" / "discrepancies.md"
    # working/ is shared staging — a permitted destination for any writer.
    writers._assert_writable("vedant", working_file)


# --- Task 1b: provenance-bearing writers over the current-value engine ---

def test_financial_fact_inserts(tmp_memory):
    out = writers.write_financial_fact(
        "vedant",
        key="income.salary",
        value="100000",
        category="income",
        cadence="monthly",
        source="onboarding_form",
        confidence="high",
        as_of="2026-06-01",
        dedup_id="d1",
    )
    assert out is UpsertOutcome.INSERTED
    text = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "## income.salary" in text
    assert "- value: 100000" in text
    assert "- category: income" in text
    assert "- source: onboarding_form" in text
    assert "- status: CURRENT" in text


def test_financial_fact_lower_authority_stages(tmp_memory):
    writers.write_financial_fact(
        "vedant", key="income.salary", value="105000", category="income",
        cadence="monthly", source="document_upload", confidence="high",
        as_of="2026-06-01", dedup_id="up",
    )
    out = writers.write_financial_fact(
        "vedant", key="income.salary", value="90000", category="income",
        cadence="monthly", source="conversation", confidence="low",
        as_of="2026-06-05", dedup_id="conv",
    )
    assert out is UpsertOutcome.STAGED
    fin = (tmp_memory / "members" / "vedant" / "finances.md").read_text()
    assert "- value: 90000" not in fin  # upload value untouched
    disc = (tmp_memory / "working" / "discrepancies.md").read_text()
    assert "income.salary" in disc
    assert "document_upload" in disc


def test_financial_fact_cross_member_raises(tmp_memory, monkeypatch):
    bad = settings.resolve(settings.memory_dir) / "members" / "mom" / "finances.md"
    monkeypatch.setattr(writers, "_member_file", lambda writer, fname: bad)
    with pytest.raises(CrossMemberWriteError):
        writers.write_financial_fact(
            "vedant", key="income.salary", value="1", category="income",
            cadence="monthly", source="conversation", confidence="low",
            as_of="2026-06-01", dedup_id="x",
        )


def test_portfolio_snapshot_writes_dated_block(tmp_memory):
    out = writers.write_portfolio_snapshot(
        "vedant",
        as_of="2026-06-08",
        holdings={"equity": "500000", "mf_sip": "300000"},
        source="document_upload",
        confidence="high",
        dedup_id="snap",
    )
    assert out is True
    text = (tmp_memory / "members" / "vedant" / "portfolio_snapshots.md").read_text()
    assert "## as of 2026-06-08" in text
    assert "- equity: 500000" in text
    assert "- source: document_upload" in text


def test_inference_writes_keyed_by_topic(tmp_memory):
    writers.write_inference(
        "vedant",
        topic="loss_aversion",
        claim="uncomfortable with drawdowns",
        basis="panicked at a 10% dip",
        confidence="low",
        as_of="2026-06-08",
        dedup_id="inf1",
    )
    text = (tmp_memory / "members" / "vedant" / "inferences.md").read_text()
    assert "## loss_aversion" in text
    assert "- claim: uncomfortable with drawdowns" in text
    assert "- source: inference" in text


def test_risk_profile_writes_keyed_by_dimension(tmp_memory):
    writers.write_risk_profile(
        "vedant",
        dimension="risk_tolerance",
        stance="moderate",
        basis="quiz: would hold through a 10% dip",
        confidence="med",
        source="onboarding_quiz",
        as_of="2026-06-08",
        dedup_id="rp1",
    )
    text = (tmp_memory / "members" / "vedant" / "risk_profile.md").read_text()
    assert "## risk_tolerance" in text
    assert "- stance: moderate" in text
    assert "- source: onboarding_quiz" in text


def test_stage_cross_member_observation(tmp_memory):
    writers.stage_cross_member_observation(
        "vedant",
        observation="retiring next year",
        about="dad",
        date="2026-06-08",
        dedup_id="cm1",
    )
    text = (tmp_memory / "working" / "cross_member_observations.md").read_text()
    assert "retiring next year" in text
    assert "dad" in text
    assert "vedant" in text  # records who observed it
