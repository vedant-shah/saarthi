"""Persist a member's onboarding money/goals slice into their memory files.

Runs after the roster (identity) is saved. Each fact is written AS the member
(writer == member), so cross-member isolation holds (MEMORY_DATA_MODEL §7).
Idempotent via per-fact dedup ids that include the value: an unchanged re-submit
is a NOOP, a changed value supersedes the prior block.

Mapped here, through the existing writers:
  income / total spend / loans  -> finances.md (income / expense / liability)
  assets + emergency fund        -> portfolio_summary.md
  goals                          -> goals.md
  dependents' monthly support    -> finances.md (a recurring expense)

NOT mapped yet (no clean target schema): insurance (health/term cover) and the
gut-check answers -> risk_profile. Those need a schema/mapping decision.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from backend.agent import writers

_SRC = "onboarding_form"
_CONF = "high"


def _num(v) -> str | None:
    """Stringify a positive numeric amount, or None for empty/zero/non-numeric."""
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", ""))
    except ValueError:
        return None
    if n <= 0:
        return None
    return str(int(n)) if n == int(n) else str(n)


# Gut-check scoring (MEMORY_DATA_MODEL §4 risk_profile). Two scenarios feed risk
# tolerance, one feeds investment horizon. We record the behavior, never a label.
_DIP = {"buy-more": 2, "sit-tight": 1, "move-some": -1, "take-out": -2}
_FLIP = {"flip": 2, "sure": -2}
_DIP_PHRASE = {
    "buy-more": "bought more on a dip",
    "sit-tight": "held through a dip",
    "move-some": "moved some to safety on a dip",
    "take-out": "pulled out on a dip",
}
_FLIP_PHRASE = {
    "flip": "took the coin flip over a sure thing",
    "sure": "took the sure money over a coin flip",
}
_HORIZON = {"fine": "long", "uneasy": "medium", "no-way": "short"}
_HORIZON_PHRASE = {
    "fine": "fine locking money away 5 years",
    "uneasy": "uneasy but ok locking money away 5 years",
    "no-way": "needs to be able to reach their money",
}


def _risk_from_checks(checks: dict) -> dict[str, tuple[str, str, str]]:
    """Map gut-check answers to risk_profile stances:
    dimension -> (stance, basis, confidence). Missing answers are skipped, and
    fewer answers lower confidence."""
    answers = checks.get("answers") or {}
    out: dict[str, tuple[str, str, str]] = {}

    score = 0
    phrases: list[str] = []
    answered = 0
    dip = answers.get("drop")
    if dip in _DIP:
        score += _DIP[dip]
        phrases.append(_DIP_PHRASE[dip])
        answered += 1
    flip = answers.get("sure-or-flip")
    if flip in _FLIP:
        score += _FLIP[flip]
        phrases.append(_FLIP_PHRASE[flip])
        answered += 1
    if answered:
        stance = "high" if score >= 2 else "low" if score <= -2 else "moderate"
        out["risk_tolerance"] = (
            stance,
            "gut-check: " + ", ".join(phrases),
            "med" if answered == 2 else "low",
        )

    reach = answers.get("reach")
    if reach in _HORIZON:
        out["horizon"] = (_HORIZON[reach], "gut-check: " + _HORIZON_PHRASE[reach], "med")

    return out


def persist_member_data(memory_root: Path, member: str, data: dict, *, today: str) -> None:
    fin = data.get("finances") or {}

    for item in fin.get("incomes") or []:
        amount = _num(item.get("amount"))
        if not amount:
            continue
        key = item.get("key") or "other"
        writers.write_financial_fact(
            member, key=f"income.{key}", value=amount, category="income",
            cadence=item.get("cadence") or "monthly",
            source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:income:{key}:{amount}",
        )

    spend = _num(fin.get("spend"))
    if spend:
        writers.write_financial_fact(
            member, key="expense.total", value=spend, category="expense",
            cadence="monthly", source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:expense:total:{spend}",
        )

    for item in fin.get("loans") or []:
        key = item.get("key") or "other"
        remaining = _num(item.get("remaining"))
        emi = _num(item.get("emi"))
        if remaining:
            writers.write_financial_fact(
                member, key=f"liability.{key}", value=remaining, category="liability",
                cadence="one_time", source=_SRC, confidence=_CONF, as_of=today,
                dedup_id=f"onb:liab:{key}:{remaining}",
            )
        if emi:
            writers.write_financial_fact(
                member, key=f"liability.{key}.emi", value=emi, category="liability",
                cadence="monthly", source=_SRC, confidence=_CONF, as_of=today,
                dedup_id=f"onb:liab_emi:{key}:{emi}",
            )

    for item in fin.get("assets") or []:
        amount = _num(item.get("amount"))
        if not amount:
            continue
        key = item.get("key") or "other"
        writers.write_asset(
            member, key=key, value=amount, asset_class=key,
            source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:asset:{key}:{amount}",
        )

    ef = _num(fin.get("emergencyFund"))
    if ef:
        writers.write_asset(
            member, key="cash.emergency_fund", value=ef, asset_class="cash",
            source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:asset:ef:{ef}",
        )

    support = _num(data.get("supportMonthly"))
    if support:
        writers.write_financial_fact(
            member, key="expense.dependents_support", value=support,
            category="expense", cadence="monthly", source=_SRC, confidence=_CONF,
            as_of=today, dedup_id=f"onb:expense:dep:{support}",
        )

    for goal in data.get("goals") or []:
        title = (goal.get("title") or "").strip()
        if not title:
            continue
        amount = _num(goal.get("amount"))
        target = amount if (amount and not goal.get("notSure")) else ""
        writers.write_goal(
            member, title=title, target=target, horizon=goal.get("bucket") or "",
            source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:goal:{title.lower()}:{target}",
        )

    # Insurance -> profile.md (product decision: insurance lives in profile).
    for kind in ("health", "term"):
        ins = fin.get(kind) or {}
        covered = ins.get("covered")
        cover = _num(ins.get("cover"))
        if covered is None and not cover:
            continue
        writers.write_insurance(
            member, kind=kind, covered=bool(covered), cover=cover,
            source=_SRC, confidence=_CONF, as_of=today,
            dedup_id=f"onb:ins:{kind}:{covered}:{cover}",
        )

    # Gut-check -> risk_profile.md (tolerance + horizon), sourced as the quiz.
    for dim, (stance, basis, conf) in _risk_from_checks(data.get("checks") or {}).items():
        writers.write_risk_profile(
            member, dimension=dim, stance=stance, basis=basis,
            confidence=conf, source="onboarding_quiz", as_of=today,
            dedup_id=f"onb:risk:{dim}:{stance}",
        )


def _valid_iso_date(value) -> str | None:
    """Return an ISO `YYYY-MM-DD` string unchanged, else None."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def persist_portfolio_snapshot(
    member: str, holdings: list[dict], *, statement_date: str | None, today: str
) -> str:
    """Append a dated holdings snapshot (from an uploaded document) into
    portfolio_snapshots.md, dated by the document's statement date when valid,
    else today. Individual holding names are kept here even though the live
    register (portfolio_summary) rolls them up by class. Returns the as_of used.

    Idempotent: re-posting the same holdings for the same date is a NOOP via the
    dedup id; an empty holdings list writes nothing."""
    as_of = _valid_iso_date(statement_date) or today
    fields: dict[str, str] = {}
    for h in holdings or []:
        label = (h.get("label") or "").strip()
        amount = _num(h.get("amount"))
        if label and amount:
            fields[label] = amount
    if fields:
        writers.write_portfolio_snapshot(
            member,
            as_of=as_of,
            holdings=fields,
            source="document_upload",
            confidence="high",
            dedup_id=f"docsnap:{as_of}:" + ",".join(sorted(fields)),
        )
    return as_of
