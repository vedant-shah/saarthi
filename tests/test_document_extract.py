"""Unit tests for the uploaded-document holding extractor.

The deterministic parts (upload validation, text rendering, normalization of the
model's raw output) are tested directly. The single LLM call is stood in for by
FakeProvider, so these tests never touch the network and assert two things:
the right payload reaches the model, and its raw output is normalized cleanly.
"""
from __future__ import annotations

import io

import openpyxl
import pytest

from backend.agent import document_extract as de
from backend.config import settings
from tests.conftest import FakeProvider


# --- validate_upload ---------------------------------------------------------


def test_validate_accepts_known_types_case_insensitive():
    assert de.validate_upload("statement.csv", 100) == ".csv"
    assert de.validate_upload("PORTFOLIO.XLSX", 100) == ".xlsx"
    assert de.validate_upload("cas.pdf", 100) == ".pdf"


def test_validate_rejects_unknown_type():
    with pytest.raises(de.UnsupportedDocument):
        de.validate_upload("notes.docx", 100)


def test_validate_rejects_empty_and_oversize():
    with pytest.raises(de.UnsupportedDocument):
        de.validate_upload("a.csv", 0)
    with pytest.raises(de.UnsupportedDocument):
        de.validate_upload("a.csv", de.MAX_UPLOAD_BYTES + 1)


# --- normalize_holdings ------------------------------------------------------


def test_normalize_drops_bad_rows_and_clamps_class():
    out = de.normalize_holdings(
        [
            {"label": "HDFC Flexi Cap", "amount": "2,50,000", "asset_class": "mf-sip"},
            {"label": "   ", "amount": 5000, "asset_class": "stocks"},  # no label
            {"label": "Bad", "amount": "abc", "asset_class": "gold"},  # bad amount
            {"label": "Zero", "amount": 0, "asset_class": "stocks"},  # non-positive
            {"label": "Mystery", "amount": 7500, "asset_class": "crypto"},  # class->other
            "garbage",  # not a dict
        ]
    )
    assert out == [
        {"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"},
        {"label": "Mystery", "amount": 7500, "asset_class": "other"},
    ]


def test_normalize_non_list_returns_empty():
    assert de.normalize_holdings(None) == []
    assert de.normalize_holdings({"holdings": []}) == []


def test_normalize_keeps_fractional_amounts():
    out = de.normalize_holdings([{"label": "Gold", "amount": "12345.5", "asset_class": "gold"}])
    assert out == [{"label": "Gold", "amount": 12345.5, "asset_class": "gold"}]


# --- extract_holdings (orchestration via FakeProvider) -----------------------


async def test_extract_csv_sends_text_and_normalizes():
    raw = b"Fund,Value\nHDFC Flexi Cap,250000\n"
    provider = FakeProvider(
        {
            "holdings": [
                {"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"},
                {"label": "Reliance shares", "amount": 120000, "asset_class": "stocks"},
            ]
        }
    )
    result = await de.extract_holdings(provider, filename="cas.csv", raw_bytes=raw)

    assert result.holdings == [
        {"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"},
        {"label": "Reliance shares", "amount": 120000, "asset_class": "stocks"},
    ]
    # CSV contents must reach the model as plain text, not a document block.
    content = provider.last_kwargs["messages"][0]["content"]
    assert isinstance(content, str)
    assert "HDFC Flexi Cap" in content


async def test_extract_xlsx_renders_cells_to_text():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Holding", "Value"])
    ws.append(["ICICI Bluechip", 95000])
    buf = io.BytesIO()
    wb.save(buf)

    provider = FakeProvider({"holdings": [{"label": "ICICI Bluechip", "amount": 95000, "asset_class": "mf-sip"}]})
    result = await de.extract_holdings(provider, filename="portfolio.xlsx", raw_bytes=buf.getvalue())

    assert result.holdings == [{"label": "ICICI Bluechip", "amount": 95000, "asset_class": "mf-sip"}]
    content = provider.last_kwargs["messages"][0]["content"]
    assert isinstance(content, str)
    assert "ICICI Bluechip" in content
    assert "95000" in content


async def test_extract_pdf_extracts_text_with_pymupdf():
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Axis Bluechip Fund 185000")
    raw = doc.tobytes()
    doc.close()

    provider = FakeProvider(
        {"holdings": [{"label": "Axis Bluechip Fund", "amount": 185000, "asset_class": "mf-sip"}]}
    )
    result = await de.extract_holdings(provider, filename="cas.pdf", raw_bytes=raw)

    assert result.holdings == [{"label": "Axis Bluechip Fund", "amount": 185000, "asset_class": "mf-sip"}]
    # PDF text is extracted locally and sent as plain text, not a document block.
    content = provider.last_kwargs["messages"][0]["content"]
    assert isinstance(content, str)
    assert "Axis Bluechip Fund" in content


async def test_extract_uses_document_model():
    provider = FakeProvider({"holdings": []})
    await de.extract_holdings(provider, filename="cas.csv", raw_bytes=b"a,b\n1,2\n")
    assert provider.last_kwargs["model"] == settings.document_model


# --- password-protected PDFs (CAS statements are almost always encrypted) -----


def _encrypted_pdf(text: str, user_pw: str) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    raw = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw=user_pw
    )
    doc.close()
    return raw


async def test_extract_encrypted_pdf_without_password_raises():
    raw = _encrypted_pdf("HDFC Flexi Cap 250000", "secret")
    with pytest.raises(de.PdfPasswordRequired) as exc:
        await de.extract_holdings(FakeProvider(), filename="cas.pdf", raw_bytes=raw)
    assert exc.value.provided is False


async def test_extract_encrypted_pdf_with_wrong_password_raises():
    raw = _encrypted_pdf("HDFC Flexi Cap 250000", "secret")
    with pytest.raises(de.PdfPasswordRequired) as exc:
        await de.extract_holdings(
            FakeProvider(), filename="cas.pdf", raw_bytes=raw, password="nope"
        )
    assert exc.value.provided is True


async def test_extract_encrypted_pdf_with_correct_password_extracts():
    raw = _encrypted_pdf("HDFC Flexi Cap 250000", "secret")
    provider = FakeProvider(
        {"holdings": [{"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"}]}
    )
    result = await de.extract_holdings(
        provider, filename="cas.pdf", raw_bytes=raw, password="secret"
    )
    assert result.holdings == [{"label": "HDFC Flexi Cap", "amount": 250000, "asset_class": "mf-sip"}]
    assert "HDFC Flexi Cap" in provider.last_kwargs["messages"][0]["content"]


# --- statement date -----------------------------------------------------------


async def test_extract_returns_valid_statement_date():
    provider = FakeProvider({"holdings": [], "statement_date": "2026-05-31"})
    result = await de.extract_holdings(provider, filename="cas.csv", raw_bytes=b"a,b\n1,2\n")
    assert result.statement_date == "2026-05-31"


async def test_extract_invalid_statement_date_is_none():
    provider = FakeProvider({"holdings": [], "statement_date": "last month"})
    result = await de.extract_holdings(provider, filename="cas.csv", raw_bytes=b"a,b\n1,2\n")
    assert result.statement_date is None


# --- document type ------------------------------------------------------------


async def test_extract_returns_document_type():
    provider = FakeProvider({"holdings": [], "document_type": "cas"})
    result = await de.extract_holdings(provider, filename="cas.csv", raw_bytes=b"a,b\n1,2\n")
    assert result.document_type == "cas"


async def test_extract_unknown_document_type_is_other():
    provider = FakeProvider({"holdings": [], "document_type": "spreadsheet"})
    result = await de.extract_holdings(provider, filename="x.csv", raw_bytes=b"a,b\n1,2\n")
    assert result.document_type == "other"


# --- grouping across statements ----------------------------------------------


async def test_group_merges_overlap_and_normalizes():
    sources = [
        {
            "document_type": "cas",
            "statement_date": "2026-05-31",
            "holdings": [{"label": "HDFC Flexi Cap", "amount": 150000, "asset_class": "mf-sip"}],
        },
        {
            "document_type": "demat",
            "statement_date": "2026-06-15",
            "holdings": [{"label": "HDFC Flexi Cap", "amount": 160000, "asset_class": "mf-sip"}],
        },
    ]
    provider = FakeProvider(
        {
            "holdings": [
                {"label": "HDFC Flexi Cap", "amount": 160000, "asset_class": "mf-sip", "sources": ["cas", "demat"]}
            ]
        }
    )
    out = await de.group_holdings(provider, sources=sources)
    assert out == [
        {"label": "HDFC Flexi Cap", "amount": 160000, "asset_class": "mf-sip", "sources": ["cas", "demat"]}
    ]
    # Both statements are shown to the grouping model.
    content = provider.last_kwargs["messages"][0]["content"]
    assert "HDFC Flexi Cap" in content and "cas" in content


async def test_group_single_holding_skips_the_model():
    sources = [
        {"document_type": "amc", "statement_date": None, "holdings": [{"label": "Gold", "amount": 50000, "asset_class": "gold"}]}
    ]
    provider = FakeProvider({"holdings": []})
    out = await de.group_holdings(provider, sources=sources)
    assert out == [{"label": "Gold", "amount": 50000, "asset_class": "gold"}]
    assert provider.calls == 0  # nothing to merge, so no LLM call


async def test_group_falls_back_to_raw_merge_on_no_tool_call():
    class NoneProvider(FakeProvider):
        async def complete_json(self, **kwargs):
            return None

    sources = [
        {"document_type": "demat", "statement_date": None, "holdings": [{"label": "TCS", "amount": 80000, "asset_class": "stocks"}]},
        {"document_type": "demat", "statement_date": None, "holdings": [{"label": "Infosys", "amount": 60000, "asset_class": "stocks"}]},
    ]
    out = await de.group_holdings(NoneProvider(), sources=sources)
    assert out == [
        {"label": "TCS", "amount": 80000, "asset_class": "stocks"},
        {"label": "Infosys", "amount": 60000, "asset_class": "stocks"},
    ]


async def test_extract_unsupported_type_raises():
    with pytest.raises(de.UnsupportedDocument):
        await de.extract_holdings(FakeProvider(), filename="notes.docx", raw_bytes=b"hello")


async def test_extract_no_tool_call_returns_empty():
    class NoneProvider(FakeProvider):
        async def complete_json(self, **kwargs):
            return None

    result = await de.extract_holdings(NoneProvider(), filename="cas.csv", raw_bytes=b"Fund,Value\nX,1\n")
    assert result.holdings == []
