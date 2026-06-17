"""Tests for POST /api/onboarding/extract-document.

The endpoint validates the member and file, runs the extractor, and returns the
holdings for client-side review. The LLM is never called here: the happy path
monkeypatches document_extract.extract_holdings, and the rejection paths fail
before any model call.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend import main
from backend.agent.document_extract import Extraction
from backend.main import app


def test_extract_document_rejects_invalid_member_id(tmp_memory) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/extract-document",
            headers={"X-Member-Id": "../etc"},
            files={"file": ("cas.csv", b"Fund,Value\nHDFC,250000\n", "text/csv")},
        )
    assert resp.status_code == 400


def test_extract_document_rejects_unsupported_type(tmp_memory) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/extract-document",
            headers={"X-Member-Id": "vedant"},
            files={"file": ("notes.docx", b"not a statement", "application/octet-stream")},
        )
    assert resp.status_code == 400


def test_extract_document_returns_holdings(tmp_memory, monkeypatch) -> None:
    async def fake_extract(provider, *, filename, raw_bytes, password=None):
        assert filename == "cas.csv"
        assert raw_bytes == b"Fund,Value\nHDFC,250000\n"
        return Extraction(
            holdings=[{"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"}],
            statement_date="2026-05-31",
        )

    monkeypatch.setattr(main.document_extract, "extract_holdings", fake_extract)

    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/extract-document",
            headers={"X-Member-Id": "vedant"},
            files={"file": ("cas.csv", b"Fund,Value\nHDFC,250000\n", "text/csv")},
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "holdings": [{"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"}],
        "statement_date": "2026-05-31",
        "document_type": "other",
    }


def test_group_holdings_endpoint_returns_merged(tmp_memory, monkeypatch) -> None:
    async def fake_group(provider, *, sources):
        assert len(sources) == 2
        return [
            {"label": "HDFC Flexi Cap", "amount": 160000, "asset_class": "mf-sip", "sources": ["cas", "demat"]}
        ]

    monkeypatch.setattr(main.document_extract, "group_holdings", fake_group)

    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/group-holdings",
            headers={"X-Member-Id": "vedant"},
            json={
                "sources": [
                    {"document_type": "cas", "statement_date": "2026-05-31", "holdings": []},
                    {"document_type": "demat", "statement_date": "2026-06-15", "holdings": []},
                ]
            },
        )
    assert resp.status_code == 200
    assert resp.json() == {
        "holdings": [
            {"label": "HDFC Flexi Cap", "amount": 160000, "asset_class": "mf-sip", "sources": ["cas", "demat"]}
        ]
    }


def test_extract_document_encrypted_pdf_needs_password(tmp_memory) -> None:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "HDFC Flexi Cap 250000")
    raw = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret"
    )
    doc.close()

    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/extract-document",
            headers={"X-Member-Id": "vedant"},
            files={"file": ("cas.pdf", raw, "application/pdf")},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "pdf_password_required"


def test_extract_document_forwards_password(tmp_memory, monkeypatch) -> None:
    seen = {}

    async def fake_extract(provider, *, filename, raw_bytes, password=None):
        seen["password"] = password
        return Extraction(holdings=[], statement_date=None)

    monkeypatch.setattr(main.document_extract, "extract_holdings", fake_extract)

    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/extract-document",
            headers={"X-Member-Id": "vedant"},
            files={"file": ("cas.pdf", b"%PDF-1.4", "application/pdf")},
            data={"password": "secret"},
        )
    assert resp.status_code == 200
    assert seen["password"] == "secret"


def test_portfolio_snapshot_saves_under_statement_date(tmp_memory) -> None:
    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/portfolio-snapshot",
            headers={"X-Member-Id": "vedant"},
            json={
                "holdings": [
                    {"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"}
                ],
                "statement_date": "2026-05-31",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["as_of"] == "2026-05-31"
    snapshot = (tmp_memory / "members" / "vedant" / "portfolio_snapshots.md").read_text()
    assert "2026-05-31" in snapshot
    assert "HDFC Flexi Cap" in snapshot


def test_portfolio_snapshot_falls_back_to_today(tmp_memory) -> None:
    from datetime import date

    with TestClient(app) as client:
        resp = client.post(
            "/api/onboarding/portfolio-snapshot",
            headers={"X-Member-Id": "vedant"},
            json={
                "holdings": [{"label": "Gold", "amount": 50000, "asset_class": "gold"}],
                "statement_date": None,
            },
        )
    assert resp.status_code == 200
    assert resp.json()["as_of"] == date.today().isoformat()
