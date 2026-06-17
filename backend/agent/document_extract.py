"""Extract investment holdings from an uploaded document (CSV / XLSX / PDF).

Holdings/assets only — the scope of the onboarding savings step. The
deterministic parts live here and are unit-tested: turning a file into something
the model can read (CSV/XLSX -> text, PDF -> a base64 document block) and
normalizing the model's raw output into clean holding rows. One LLM call
classifies each holding into an onboarding asset-class key and reads its rupee
value. Nothing is written to memory: the caller returns the holdings to the
client for review, and only confirmed values flow through the normal save path.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date

from backend.agent.llm_provider import LLMProvider, SystemBlock
from backend.config import settings

logger = logging.getLogger(__name__)

# Reject anything larger up front — these are personal statements, not archives.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

_CSV_EXT = ".csv"
_XLSX_EXT = ".xlsx"
_PDF_EXT = ".pdf"
ALLOWED_EXTENSIONS = (_CSV_EXT, _XLSX_EXT, _PDF_EXT)

# The asset-class keys the savings screen knows (frontend moneyCatalog
# ASSET_CLASSES), plus "other" for anything that does not fit. The model must
# pick from these so extracted rows drop straight into the existing asset rows.
ASSET_CLASS_KEYS = ("bank-fd", "mf-sip", "stocks", "gold", "property", "pf", "other")

# Document kinds. The grouping pass uses these to reason about overlaps: a CAS is
# consolidated, so its funds overlap with any AMC/demat statement of the same funds.
DOC_TYPES = ("cas", "demat", "amc", "bank", "other")


@dataclass(frozen=True)
class Extraction:
    """What one document yielded: the holdings, the statement's as-of date (ISO
    `YYYY-MM-DD`, or None when none was readable), and the document kind."""

    holdings: list[dict]
    statement_date: str | None
    document_type: str = "other"


class UnsupportedDocument(ValueError):
    """An upload we will not process (wrong type, empty, or too large)."""


class PdfPasswordRequired(Exception):
    """An encrypted PDF needs a (correct) password to read. `provided` is False
    when none was supplied, True when one was but it was wrong — so the caller
    can tell 'ask for the password' apart from 'that password was wrong'."""

    def __init__(self, *, provided: bool) -> None:
        self.provided = provided
        super().__init__("pdf password required")


def _extension(filename: str) -> str:
    name = (filename or "").lower().strip()
    dot = name.rfind(".")
    return name[dot:] if dot != -1 else ""


def validate_upload(filename: str, size: int) -> str:
    """Return the lowercased extension for an accepted upload, else raise
    UnsupportedDocument. Validates type and size only — never reads content."""
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedDocument(
            f"unsupported file type: {filename!r} (allowed: csv, xlsx, pdf)"
        )
    if size <= 0:
        raise UnsupportedDocument("empty file")
    if size > MAX_UPLOAD_BYTES:
        raise UnsupportedDocument(f"file too large: {size} bytes (max {MAX_UPLOAD_BYTES})")
    return ext


def _coerce_amount(value) -> float | int | None:
    """Parse a rupee amount, tolerating commas and a ₹ sign. Returns an int when
    whole, else a float; None for anything non-positive or unparseable."""
    if value is None:
        return None
    try:
        n = float(str(value).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return None
    if n <= 0:
        return None
    return int(n) if n == int(n) else n


def _normalize_date(value) -> str | None:
    """Accept an ISO `YYYY-MM-DD` date string, returning it normalized; anything
    else (empty, prose, a bad date) becomes None so the caller falls back to today."""
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _normalize_doc_type(value) -> str:
    """Clamp the model's document-kind guess to a known type, else 'other'."""
    return value if value in DOC_TYPES else "other"


def normalize_holdings(raw_holdings) -> list[dict]:
    """Clean the model's raw holding list: keep rows with a label and a positive
    amount, coerce the amount, and clamp asset_class to a known key (unknown ->
    "other"). Returns fresh dicts; never mutates the input."""
    out: list[dict] = []
    if not isinstance(raw_holdings, list):
        return out
    for item in raw_holdings:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        amount = _coerce_amount(item.get("amount"))
        if not label or amount is None:
            continue
        asset_class = item.get("asset_class")
        if asset_class not in ASSET_CLASS_KEYS:
            asset_class = "other"
        out.append({"label": label, "amount": amount, "asset_class": asset_class})
    return out


def _csv_to_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace").strip()


def _xlsx_to_text(raw: bytes) -> str:
    """Render every non-empty row of every sheet as a comma-joined line."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for ws in wb.worksheets:
            lines.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(cell.strip() for cell in cells):
                    lines.append(",".join(cells))
    finally:
        wb.close()
    return "\n".join(lines).strip()


_INSTRUCTION = (
    "Extract every investment holding and its current value from this document."
)

_SYSTEM = (
    "You read a financial document a family uploaded and extract ONLY their "
    "investment holdings and the current value of each. Examples of holdings: "
    "mutual fund folios, stocks/shares, fixed deposits, gold, property, "
    "provident fund. Classify each into one of: bank-fd, mf-sip, stocks, gold, "
    "property, pf, other. All values are in Indian rupees — report a plain "
    "number with no symbols or commas. Keep each holding's name SHORT (2-4 "
    "words): the fund house and scheme or the company, e.g. 'HDFC Flexi Cap' "
    "or 'Reliance shares' — not the full legal name with 'Direct Plan - Growth "
    "Option' and folio numbers. Do NOT invent values you cannot see in the "
    "document; if it lists no holdings, return an empty list. Also classify the "
    "whole document as one of: cas (a Consolidated Account Statement listing all "
    "mutual funds across fund houses), demat (a broker/depository statement, "
    "mostly stocks), amc (a single fund house's statement), bank (a bank or "
    "fixed-deposit statement), or other."
)

_EXTRACT_TOOL = {
    "name": "record_holdings",
    "description": "Record the investment holdings and current values found in the document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "holdings": {
                "type": "array",
                "description": "One entry per holding found; empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "Short name of the holding, 2-4 words, e.g. 'HDFC Flexi Cap' or 'Reliance shares' — not the full legal scheme name.",
                        },
                        "amount": {
                            "type": "number",
                            "description": "Current value in rupees as a plain number (no symbols or commas).",
                        },
                        "asset_class": {
                            "type": "string",
                            "enum": list(ASSET_CLASS_KEYS),
                            "description": "Best-fit asset class for this holding.",
                        },
                    },
                    "required": ["label", "amount", "asset_class"],
                },
            },
            "statement_date": {
                "type": "string",
                "description": "The statement / as-of date printed on the document, as YYYY-MM-DD. Empty string if the document shows no date.",
            },
            "document_type": {
                "type": "string",
                "enum": list(DOC_TYPES),
                "description": "The kind of document: cas (consolidated, all mutual funds), demat (broker, mostly stocks), amc (one fund house), bank, or other.",
            },
        },
        "required": ["holdings", "statement_date", "document_type"],
    },
}


def _pdf_to_text(raw: bytes, password: str | None = None) -> str:
    """Extract the text layer from a digital PDF with PyMuPDF. CAS statements are
    almost always encrypted, so unlock with `password` first and raise
    PdfPasswordRequired when it is missing or wrong (the caller turns that into a
    'needs password' response instead of a 500). Scanned/image-only PDFs yield
    little or nothing — those would need OCR, which is out of scope."""
    import pymupdf

    doc = pymupdf.open(stream=raw, filetype="pdf")
    try:
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                raise PdfPasswordRequired(provided=bool(password))
        return "\n".join(page.get_text() for page in doc).strip()
    finally:
        doc.close()


def _build_user_content(ext: str, raw_bytes: bytes, password: str | None = None) -> str:
    """Render the upload to plain text (instruction + document contents). Every
    accepted type becomes text, so one cheap text prompt handles all three —
    which also lets the extraction run on a small, fast model."""
    if ext == _CSV_EXT:
        text = _csv_to_text(raw_bytes)
    elif ext == _XLSX_EXT:
        text = _xlsx_to_text(raw_bytes)
    else:  # PDF
        text = _pdf_to_text(raw_bytes, password)
    return f"{_INSTRUCTION}\n\nDocument contents:\n{text}"


async def extract_holdings(
    provider: LLMProvider, *, filename: str, raw_bytes: bytes, password: str | None = None
) -> Extraction:
    """Extract and normalize the investment holdings from an uploaded document.

    Raises UnsupportedDocument for a bad file type/size, and PdfPasswordRequired
    for an encrypted PDF whose password is missing or wrong. Returns [] when the
    model makes no tool call (a failed extraction) or finds no holdings — both
    are 'nothing to review', never an error the caller must handle."""
    ext = validate_upload(filename, len(raw_bytes))
    content = _build_user_content(ext, raw_bytes, password)
    raw = await provider.complete_json(
        system=[SystemBlock(text=_SYSTEM)],
        messages=[{"role": "user", "content": content}],
        tool=_EXTRACT_TOOL,
        model=settings.document_model,
        max_tokens=4000,
    )
    if raw is None:
        logger.warning("document extract: no tool call for %s", filename)
        return Extraction(holdings=[], statement_date=None)
    return Extraction(
        holdings=normalize_holdings(raw.get("holdings")),
        statement_date=_normalize_date(raw.get("statement_date")),
        document_type=_normalize_doc_type(raw.get("document_type")),
    )


# --- Grouping across multiple statements -------------------------------------

_GROUP_SYSTEM = (
    "You are merging investment holdings pulled from one or more financial "
    "statements a family uploaded, so each real holding appears exactly once. "
    "KEY FACT: a CAS (Consolidated Account Statement) ALREADY lists every mutual "
    "fund the person holds across all fund houses. So if a mutual fund appears "
    "in a CAS and also in another statement (an AMC statement, a demat holding, "
    "etc.), that is the SAME holding shown twice — an overlap. Keep it ONCE and "
    "do NOT add the values together; prefer the most recent value. Only add "
    "values together when you are confident the entries are genuinely different "
    "holdings, e.g. the same stock held in two different demat accounts. When "
    "unsure, treat it as an overlap and keep one. Inflating the total is the "
    "worse mistake. Preserve each kept holding's short name and asset class, and "
    "list which statements it came from."
)

_GROUP_TOOL = {
    "name": "record_grouped_holdings",
    "description": "Record the merged holdings, each real holding appearing once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "holdings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Short name of the holding."},
                        "amount": {"type": "number", "description": "Value in rupees, a plain number."},
                        "asset_class": {
                            "type": "string",
                            "enum": list(ASSET_CLASS_KEYS),
                            "description": "Best-fit asset class.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Which statements this holding came from, e.g. ['cas', 'demat'].",
                        },
                    },
                    "required": ["label", "amount", "asset_class", "sources"],
                },
            }
        },
        "required": ["holdings"],
    },
}


def _normalize_grouped(raw_holdings) -> list[dict]:
    """Like normalize_holdings, but also keeps a cleaned `sources` list (which
    statements each merged holding came from)."""
    out: list[dict] = []
    if not isinstance(raw_holdings, list):
        return out
    for item in raw_holdings:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        amount = _coerce_amount(item.get("amount"))
        if not label or amount is None:
            continue
        asset_class = item.get("asset_class")
        if asset_class not in ASSET_CLASS_KEYS:
            asset_class = "other"
        raw_sources = item.get("sources")
        sources = (
            [str(s).strip() for s in raw_sources if str(s).strip()]
            if isinstance(raw_sources, list)
            else []
        )
        out.append(
            {"label": label, "amount": amount, "asset_class": asset_class, "sources": sources}
        )
    return out


def _render_sources(sources: list[dict]) -> str:
    lines: list[str] = []
    for i, s in enumerate(sources, 1):
        dt = s.get("document_type") or "other"
        when = s.get("statement_date") or "no date"
        lines.append(f"Statement {i}: type={dt}, as_of={when}")
        for h in s.get("holdings") or []:
            lines.append(
                f"  - {h.get('label')} | {h.get('amount')} | {h.get('asset_class')}"
            )
    return "\n".join(lines)


async def group_holdings(provider: LLMProvider, *, sources: list[dict]) -> list[dict]:
    """Merge holdings from several statements into one list, collapsing overlaps
    (CAS-aware) and only summing genuinely distinct holdings. Each source is
    {document_type, statement_date, holdings}. With 0 or 1 holdings there is
    nothing to merge, so the model is skipped. On a failed model call, falls back
    to the raw concatenation (no dedup) so the user is never blocked."""
    all_holdings = [h for s in sources for h in (s.get("holdings") or [])]
    if len(all_holdings) <= 1:
        return normalize_holdings(all_holdings)

    prompt = (
        "Merge the holdings below so each real holding appears once. Remember a "
        "CAS already consolidates all mutual funds.\n\n" + _render_sources(sources)
    )
    raw = await provider.complete_json(
        system=[SystemBlock(text=_GROUP_SYSTEM)],
        messages=[{"role": "user", "content": prompt}],
        tool=_GROUP_TOOL,
        model=settings.document_model,
        max_tokens=4000,
    )
    if raw is None:
        logger.warning("document group: no tool call; falling back to raw merge")
        return normalize_holdings(all_holdings)
    return _normalize_grouped(raw.get("holdings"))
