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
    accrue_evidence,
    append_dated_snapshot,
    append_staging,
    key_for_id,
    strip_superseded,
    upsert_current_value,
)


def _prov(source: str, confidence: str = "high", day: str = "2026-06-08") -> Provenance:
    return Provenance(source=source, confidence=confidence, as_of=day, last_updated=day)


# ---------------------------------------------------------------------------
# Provenance / authority ordering
# ---------------------------------------------------------------------------

def test_authority_ordering():
    # Self-stated facts are authoritative: a first-person conversational statement
    # outranks the onboarding form (the user is the source of truth; recency wins),
    # but uploads / brokerage syncs remain the ground-truth guardrail above it.
    assert authority_of("document_upload") == authority_of("brokerage_sync")
    assert authority_of("document_upload") > authority_of("conversation")
    assert authority_of("conversation") > authority_of("onboarding_form")
    assert authority_of("onboarding_form") == authority_of("onboarding_quiz")
    assert authority_of("onboarding_form") > authority_of("inference")


def test_conversation_supersedes_onboarding(tmp_path):
    # The behavior the reorder buys: a later conversational correction of an
    # onboarding-sourced value updates it in place (old kept as superseded
    # history), rather than staging silently.
    f = tmp_path / "finances.md"
    upsert_current_value(
        f, key="income.salary", fields={"value": "120000"},
        prov=_prov("onboarding_form", "high"), dedup_id="id_onb",
    )
    out = upsert_current_value(
        f, key="income.salary", fields={"value": "115000"},
        prov=_prov("conversation", "low"), dedup_id="id_conv",
    )
    assert out is UpsertOutcome.SUPERSEDED
    text = f.read_text()
    assert "- value: 115000" in text
    assert "- status: SUPERSEDED" in text  # old onboarding value kept as history
    current = next(b for b in text.split("## ") if "115000" in b)
    assert "status: CURRENT" in current


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


def test_lower_authority_same_value_is_noop_not_staged(tmp_path):
    # A lower-authority source that merely RESTATES the current value is NOT a
    # conflict and must not be staged. Regression: identical 120000 from
    # conversation vs an upload was wrongly flagged NEEDS_CONFIRMATION.
    f = tmp_path / "finances.md"
    disc = tmp_path / "discrepancies.md"
    upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "120000"},
        prov=_prov("document_upload", "high"),
        dedup_id="id_upload",
    )
    out = upsert_current_value(
        f,
        key="income.salary",
        fields={"value": "120000"},  # same value, lower authority
        prov=_prov("conversation", "low"),
        dedup_id="id_conv",
        discrepancies_path=disc,
    )
    assert out is UpsertOutcome.NOOP
    assert not disc.exists() or "income.salary" not in disc.read_text()
    text = f.read_text()
    assert text.count("## income.salary") == 1
    assert "- source: document_upload" in text


def test_lower_authority_normalized_same_value_is_noop(tmp_path):
    # Light normalization: "Rs 1,20,000" equals "120000", so no spurious stage.
    f = tmp_path / "finances.md"
    disc = tmp_path / "discrepancies.md"
    upsert_current_value(
        f, key="income.salary", fields={"value": "120000"},
        prov=_prov("document_upload", "high"), dedup_id="id_upload",
    )
    out = upsert_current_value(
        f, key="income.salary", fields={"value": "Rs 1,20,000"},
        prov=_prov("conversation", "low"), dedup_id="id_conv2",
        discrepancies_path=disc,
    )
    assert out is UpsertOutcome.NOOP
    assert not disc.exists()


def test_lower_authority_different_value_still_stages(tmp_path):
    # Guard must not over-merge: a genuinely different lower-authority value
    # still stages as a discrepancy.
    f = tmp_path / "finances.md"
    disc = tmp_path / "discrepancies.md"
    upsert_current_value(
        f, key="income.salary", fields={"value": "120000"},
        prov=_prov("document_upload", "high"), dedup_id="id_upload",
    )
    out = upsert_current_value(
        f, key="income.salary", fields={"value": "90000"},
        prov=_prov("conversation", "low"), dedup_id="id_conv3",
        discrepancies_path=disc,
    )
    assert out is UpsertOutcome.STAGED
    assert "income.salary" in disc.read_text()


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


# ---------------------------------------------------------------------------
# accrue_evidence — soft inference update (§10): insert-if-absent, else accrue
# (append evidence + bump confidence one notch), claim NEVER flips
# ---------------------------------------------------------------------------

def test_accrue_inserts_when_topic_absent(tmp_path):
    f = tmp_path / "inferences.md"
    out = accrue_evidence(
        f,
        key="loss_aversion",
        fields={"claim": "dislikes drawdowns"},
        prov=_prov("inference", "low"),
        dedup_id="e1",
        evidence="panicked at a 10% dip",
    )
    assert out is UpsertOutcome.INSERTED
    text = f.read_text()
    assert "## loss_aversion" in text
    assert "- claim: dislikes drawdowns" in text
    assert "- confidence: low" in text
    assert "- status: CURRENT" in text


def test_accrue_appends_evidence_and_bumps_confidence(tmp_path):
    f = tmp_path / "inferences.md"
    accrue_evidence(
        f, key="loss_aversion", fields={"claim": "dislikes drawdowns"},
        prov=_prov("inference", "low", "2026-06-08"), dedup_id="e1",
        evidence="panicked at a 10% dip",
    )
    out = accrue_evidence(
        f, key="loss_aversion", fields={"claim": "dislikes drawdowns"},
        prov=_prov("conversation", "low", "2026-06-09"), dedup_id="e2",
        evidence="sold in a panic again",
    )
    assert out is UpsertOutcome.ACCRUED
    text = f.read_text()
    # Claim unchanged, still exactly one CURRENT, confidence nudged low -> med.
    assert text.count("- claim: dislikes drawdowns") == 1
    assert text.count("- status: CURRENT") == 1
    assert "- confidence: med" in text
    assert "- confidence: low" not in text
    # Evidence trail accrued, last_updated advanced.
    assert "sold in a panic again" in text
    assert "- last_updated: 2026-06-09" in text


def test_accrue_idempotent(tmp_path):
    f = tmp_path / "inferences.md"
    accrue_evidence(
        f, key="loss_aversion", fields={"claim": "dislikes drawdowns"},
        prov=_prov("inference", "low"), dedup_id="e1", evidence="first",
    )
    kw = dict(
        key="loss_aversion", fields={"claim": "dislikes drawdowns"},
        prov=_prov("conversation", "low", "2026-06-09"), dedup_id="e2", evidence="again",
    )
    accrue_evidence(f, **kw)
    out = accrue_evidence(f, **kw)
    assert out is UpsertOutcome.NOOP
    assert f.read_text().count("again") == 1


def test_accrue_confidence_caps_at_high(tmp_path):
    f = tmp_path / "inferences.md"
    accrue_evidence(
        f, key="risk_tolerance", fields={"stance": "moderate"},
        prov=_prov("onboarding_quiz", "high"), dedup_id="r1", evidence="quiz",
    )
    out = accrue_evidence(
        f, key="risk_tolerance", fields={"stance": "moderate"},
        prov=_prov("conversation", "low", "2026-06-09"), dedup_id="r2",
        evidence="held through a dip",
    )
    assert out is UpsertOutcome.ACCRUED
    text = f.read_text()
    assert "- confidence: high" in text  # stays capped, never overflows


# --- key_for_id: map an extractor target_id back to its block's canonical key (M4) ---


def test_key_for_id_finds_block_key():
    content = (
        "## expense.total\n- value: 25000\n- status: CURRENT\n<!-- id:exp1 -->\n\n"
        "## income.salary\n- value: 120000\n- status: CURRENT\n<!-- id:inc1 -->\n"
    )
    assert key_for_id(content, "exp1") == "expense.total"
    assert key_for_id(content, "inc1") == "income.salary"


def test_key_for_id_missing_returns_none():
    content = "## expense.total\n- value: 25000\n<!-- id:exp1 -->\n"
    assert key_for_id(content, "nope") is None


def test_key_for_id_resolves_superseded_block():
    # a superseded block keeps its marker, so the id still resolves to its key
    content = "## expense.total\n- value: 25000\n- status: SUPERSEDED\n<!-- id:exp1 -->\n"
    assert key_for_id(content, "exp1") == "expense.total"


# ---------------------------------------------------------------------------
# strip_superseded — read-side filter (history stays on disk, prompt sees CURRENT)
# ---------------------------------------------------------------------------

def test_strip_superseded_drops_superseded_keeps_current():
    content = (
        "## A trip\n- target: 200000\n- status: SUPERSEDED\n<!-- id:g1 -->\n\n"
        "## A trip\n- target: 250000\n- status: CURRENT\n<!-- id:g2 -->\n"
    )
    out = strip_superseded(content)
    assert "id:g2" in out and "target: 250000" in out
    assert "id:g1" not in out and "SUPERSEDED" not in out


def test_strip_superseded_keeps_preamble_and_statusless_blocks():
    # Frontmatter/preamble and blocks without a status line (e.g. dated snapshots)
    # are untouched — only explicitly SUPERSEDED blocks are removed.
    content = (
        "intro text\n\n"
        "## as of 2026-06-01\n- nps: 50000\n<!-- id:s1 -->\n\n"
        "## income.salary\n- value: 120000\n- status: CURRENT\n<!-- id:i1 -->\n"
    )
    out = strip_superseded(content)
    assert out == content


def test_strip_superseded_empty_is_empty():
    assert strip_superseded("") == ""
