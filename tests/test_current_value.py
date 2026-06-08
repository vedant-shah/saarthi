"""
Tests for the current-value / dated-log write engine (Task 1a).

TDD: written FIRST (RED), then backend.agent.provenance + backend.agent.current_value
are implemented to make them GREEN.

The engine is path-agnostic mechanics: it takes already-resolved absolute paths
(the cross-member guard lives in writers.py and runs before calling here), so
these tests use plain tmp_path files and never touch the member tree.

Conventions mirror the other suites: asyncio_mode="auto" (none of these are
async though), no network, no real memory/ tree.
"""
from __future__ import annotations

from pathlib import Path

from backend.agent.provenance import Provenance, authority_of
from backend.agent.current_value import (
    UpsertOutcome,
    append_dated_snapshot,
    append_staging,
    upsert_current_value,
)


def _prov(source: str, confidence: str = "high", day: str = "2026-06-08") -> Provenance:
    return Provenance(source=source, confidence=confidence, as_of=day, last_updated=day)


# ---------------------------------------------------------------------------
# Provenance / authority ordering
# ---------------------------------------------------------------------------

def test_authority_ordering():
    assert authority_of("document_upload") == authority_of("brokerage_sync")
    assert authority_of("document_upload") > authority_of("onboarding_form")
    assert authority_of("onboarding_form") > authority_of("conversation")
    assert authority_of("conversation") > authority_of("inference")


# ---------------------------------------------------------------------------
# upsert_current_value — insert
# ---------------------------------------------------------------------------

def test_insert_into_new_file(tmp_path):
    f = tmp_path / "finances.md"
    out = upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "100000", "category": "income", "cadence": "monthly"},
        prov=_prov("onboarding_form"),
        dedup_id="id_salary_100k",
    )
    assert out is UpsertOutcome.INSERTED
    text = f.read_text()
    assert "## income.salary" in text
    assert "- value: 100000" in text
    assert "- source: onboarding_form" in text
    assert "- status: CURRENT" in text
    assert "<!-- id:id_salary_100k -->" in text


# ---------------------------------------------------------------------------
# upsert_current_value — idempotency
# ---------------------------------------------------------------------------

def test_same_key_value_is_noop(tmp_path):
    f = tmp_path / "finances.md"
    common = dict(
        key="income.salary",
        fields={"value": "100000"},
        prov=_prov("onboarding_form"),
        dedup_id="id_salary_100k",
    )
    upsert_current_value(f, **common)
    out = upsert_current_value(f, **common)
    assert out is UpsertOutcome.NOOP
    assert f.read_text().count("## income.salary") == 1


# ---------------------------------------------------------------------------
# upsert_current_value — supersede (equal authority)
# ---------------------------------------------------------------------------

def test_supersede_equal_authority_keeps_history(tmp_path):
    f = tmp_path / "finances.md"
    upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "100000"},
        prov=_prov("conversation", "low"),
        dedup_id="id_100k",
    )
    out = upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "120000"},
        prov=_prov("conversation", "low"),
        dedup_id="id_120k",
    )
    assert out is UpsertOutcome.SUPERSEDED
    text = f.read_text()
    # Both blocks kept; old marked SUPERSEDED, new is CURRENT.
    assert "- value: 100000" in text
    assert "- value: 120000" in text
    assert "- status: SUPERSEDED" in text
    assert text.count("- status: CURRENT") == 1


# ---------------------------------------------------------------------------
# upsert_current_value — higher authority incoming supersedes
# ---------------------------------------------------------------------------

def test_higher_authority_supersedes(tmp_path):
    f = tmp_path / "finances.md"
    upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "100000"},
        prov=_prov("conversation", "low"),
        dedup_id="id_conv",
    )
    out = upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "105000"},
        prov=_prov("document_upload", "high"),
        dedup_id="id_upload",
    )
    assert out is UpsertOutcome.SUPERSEDED
    text = f.read_text()
    assert "- source: document_upload" in text
    assert text.count("- status: CURRENT") == 1


# ---------------------------------------------------------------------------
# upsert_current_value — lower authority conflict stages, never clobbers
# ---------------------------------------------------------------------------

def test_lower_authority_conflict_stages(tmp_path):
    f = tmp_path / "finances.md"
    disc = tmp_path / "discrepancies.md"
    upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "105000"},
        prov=_prov("document_upload", "high"),
        dedup_id="id_upload",
    )
    out = upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "90000"},
        prov=_prov("conversation", "low"),
        dedup_id="id_conv",
        discrepancies_path=disc,
    )
    assert out is UpsertOutcome.STAGED
    # The current-value file is untouched: upload value still CURRENT, no new block.
    text = f.read_text()
    assert "- value: 90000" not in text
    assert text.count("## income.salary") == 1
    assert "- source: document_upload" in text
    # The conflict is recorded for confirmation.
    disc_text = disc.read_text()
    assert "income.salary" in disc_text
    assert "conversation" in disc_text
    assert "document_upload" in disc_text


# ---------------------------------------------------------------------------
# upsert_current_value — idempotent supersede / no resurrection
# ---------------------------------------------------------------------------

def test_resend_current_after_supersede_is_noop(tmp_path):
    f = tmp_path / "finances.md"
    upsert_current_value(
        f, key="k", fields={"value": "A"}, prov=_prov("conversation"), dedup_id="idA"
    )
    upsert_current_value(
        f, key="k", fields={"value": "B"}, prov=_prov("conversation"), dedup_id="idB"
    )
    # Re-send the now-current B → NOOP (already current).
    out_b = upsert_current_value(
        f, key="k", fields={"value": "B"}, prov=_prov("conversation"), dedup_id="idB"
    )
    # Re-send the old superseded A → NOOP (never resurrected).
    out_a = upsert_current_value(
        f, key="k", fields={"value": "A"}, prov=_prov("conversation"), dedup_id="idA"
    )
    assert out_b is UpsertOutcome.NOOP
    assert out_a is UpsertOutcome.NOOP
    text = f.read_text()
    assert text.count("- status: CURRENT") == 1
    assert "- value: B" in text
    # B is the current one.
    current_block = [b for b in text.split("## ") if "status: CURRENT" in b][0]
    assert "value: B" in current_block


# ---------------------------------------------------------------------------
# append_dated_snapshot — dated-log, never superseded
# ---------------------------------------------------------------------------

def test_dated_snapshot_appends(tmp_path):
    f = tmp_path / "portfolio_snapshots.md"
    out = append_dated_snapshot(
        f,
        as_of="2026-06-08",
        fields={"equity": "500000", "mf_sip": "300000"},
        prov=_prov("document_upload"),
        dedup_id="snap_0608",
    )
    assert out is True
    text = f.read_text()
    assert "## as of 2026-06-08" in text
    assert "- equity: 500000" in text
    assert "- source: document_upload" in text
    # dated-log has no superseding status.
    assert "status:" not in text


def test_dated_snapshot_idempotent(tmp_path):
    f = tmp_path / "portfolio_snapshots.md"
    kw = dict(
        as_of="2026-06-08",
        fields={"equity": "500000"},
        prov=_prov("document_upload"),
        dedup_id="snap_0608",
    )
    append_dated_snapshot(f, **kw)
    out = append_dated_snapshot(f, **kw)
    assert out is False
    assert f.read_text().count("## as of 2026-06-08") == 1


def test_dated_snapshots_two_dates_both_kept(tmp_path):
    f = tmp_path / "portfolio_snapshots.md"
    append_dated_snapshot(
        f, as_of="2026-05-01", fields={"equity": "400000"},
        prov=_prov("document_upload"), dedup_id="snap_0501",
    )
    append_dated_snapshot(
        f, as_of="2026-06-08", fields={"equity": "500000"},
        prov=_prov("document_upload"), dedup_id="snap_0608",
    )
    text = f.read_text()
    assert "## as of 2026-05-01" in text
    assert "## as of 2026-06-08" in text


# ---------------------------------------------------------------------------
# append_staging — idempotent free-form append for working/ files
# ---------------------------------------------------------------------------

def test_append_staging_idempotent(tmp_path):
    f = tmp_path / "cross_member_observations.md"
    append_staging(f, entry="dad is retiring next year", dedup_id="obs1")
    append_staging(f, entry="dad is retiring next year", dedup_id="obs1")
    text = f.read_text()
    assert "dad is retiring next year" in text
    assert text.count("<!-- id:obs1 -->") == 1
