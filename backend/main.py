"""
Family Financial Advisor — FastAPI app.

Frozen SSE event shape (Day 1):
  event: token  → data: {"text": "...chunk..."}
  event: done   → data: {"session_id": "...", "turn_id": "..."}
  event: error  → data: {"message": "..."}
"""
# SSE event shape FROZEN at end of Day 1 — do not change without updating frontend (Day 2)
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import AsyncIterator

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.agent import (
    document_extract,
    durability,
    onboarding,
    onboarding_persist,
    pipeline,
    roster,
    sessions,
)
from backend.agent.llm_provider import get_provider
from backend.agent.memory_updater import close_session
from backend.agent.pipeline import TurnDone, TurnError, TurnToken
from backend.config import settings
from backend.logging_setup import configure_logging
from backend.mdns import MdnsAdvertiser
from backend.utils import markdown_io

_log_file = configure_logging()

logger = logging.getLogger(__name__)
logger.info("logging to %s", _log_file)

# Idle poll cadence — sweep stale sessions to summarize and close them.
_IDLE_SWEEP_SECONDS = 60


async def _sweep_idle() -> None:
    """Summarize and close sessions that have gone idle past the staleness
    threshold. Disk-driven so it catches transcripts left by a prior process
    that shut down before its own sweep fired. Failures are isolated per
    session inside scan_and_close_stale."""
    await durability.scan_and_close_stale(datetime.now(timezone.utc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = AsyncIOScheduler()
    sched.add_job(_sweep_idle, "interval", seconds=_IDLE_SWEEP_SECONDS)
    sched.start()
    advertiser = await _start_mdns()
    # Fire-and-forget startup catch-up scan so sessions orphaned by a prior
    # shutdown are summarized quickly, without blocking the first /health check.
    _startup_task: asyncio.Task = asyncio.create_task(_startup_scan())
    try:
        yield
    finally:
        _startup_task.cancel()
        try:
            await _startup_task
        except (asyncio.CancelledError, Exception):
            pass
        if advertiser is not None:
            await asyncio.to_thread(advertiser.stop)
        sched.shutdown(wait=False)


async def _start_mdns() -> MdnsAdvertiser | None:
    """Advertise the app's Bonjour name so LAN devices can reach it by name.
    Registration blocks (it probes for name conflicts), so it runs off the event
    loop. Best effort: a network hiccup must never stop the app from booting."""
    if not settings.mdns_enabled:
        return None
    advertiser = MdnsAdvertiser(settings.mdns_name, settings.mdns_port)
    try:
        ok = await asyncio.to_thread(advertiser.start)
    except Exception:
        logger.exception("mDNS advertise failed; continuing without it")
        return None
    return advertiser if ok else None


async def _startup_scan() -> None:
    """Catch-up scan run once at startup. Exceptions are logged, not lost."""
    try:
        closed = await durability.scan_and_close_stale(datetime.now(timezone.utc))
        if closed:
            logger.info("startup scan: closed %d stale session(s)", closed)
    except Exception:
        logger.exception("startup scan failed")


app = FastAPI(title="Family Financial Advisor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_provider = get_provider()


class ChatRequest(BaseModel):
    message: str
    # Swipe-to-reply: the message being replied to and who said it ("assistant"
    # = the advisor, else the member's own). Optional; absent on normal turns.
    quoted_text: str | None = None
    quoted_role: str | None = None


class SessionCloseRequest(BaseModel):
    member: str | None = None


# Member ids are used as path segments under memory/ and sessions/ — restrict
# to a safe slug so a crafted X-Member-Id can't traverse outside those trees.
_MEMBER_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _validate_member_id(member: str) -> None:
    if not _MEMBER_ID_RE.fullmatch(member):
        raise HTTPException(status_code=400, detail=f"invalid member id: {member}")


def _assert_member_exists(member: str) -> None:
    _validate_member_id(member)
    member_dir = settings.resolve(settings.memory_dir) / "members" / member
    if not member_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"unknown member: {member}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.main_agent_model}


@app.get("/api/members")
def list_members() -> dict:
    return {"members": markdown_io.list_member_dirs(settings.resolve(settings.memory_dir))}


@app.get("/api/history")
def history(x_member_id: str = Header(..., alias="X-Member-Id")) -> dict:
    _assert_member_exists(x_member_id)
    now = time.monotonic()
    active_sid = sessions.get_active(x_member_id, now)
    if active_sid is None:
        # In-memory state may have been wiped (e.g. a backend restart). Resume the
        # most recent unclosed, non-stale session from its transcript so the
        # client doesn't silently lose the conversation. Returns None if there's
        # nothing fresh to resume.
        active_sid = durability.adopt_recent_session(
            x_member_id, now, datetime.now(timezone.utc)
        )
    if active_sid is None:
        return {"session_id": None, "messages": []}
    return {
        "session_id": active_sid,
        "messages": sessions.get_history(x_member_id, active_sid),
    }


@app.get("/api/onboarding/status")
def onboarding_status(x_member_id: str = Header(..., alias="X-Member-Id")) -> dict:
    _assert_member_exists(x_member_id)
    finished = onboarding.is_complete(
        settings.resolve(settings.memory_dir), x_member_id
    )
    return {"finished": finished}


@app.post("/api/onboarding/complete")
def onboarding_complete(x_member_id: str = Header(..., alias="X-Member-Id")) -> dict:
    _assert_member_exists(x_member_id)
    onboarding.mark_complete(settings.resolve(settings.memory_dir), x_member_id)
    return {"finished": True}


class RosterMember(BaseModel):
    name: str
    relationship: str | None = None
    age: int | None = None
    earns: bool = False
    occupation: str | None = None
    livesElsewhere: bool = False
    isSelf: bool = False
    moneyComfort: str | None = None
    id: str | None = None  # canonical id when re-submitting a known member


class RosterRequest(BaseModel):
    members: list[RosterMember]


@app.post("/api/onboarding/roster")
def onboarding_roster(req: RosterRequest) -> dict:
    """Persist the onboarding "who" phase: create/update each member's dir +
    identity profile.md, and return the canonical ids so the client can re-key
    its local draft. Create-or-update only — never deletes."""
    if sum(1 for m in req.members if m.isSelf) != 1:
        raise HTTPException(
            status_code=400, detail="exactly one member must be marked as self"
        )
    for m in req.members:
        if m.id is not None:
            _validate_member_id(m.id)
    persisted = roster.persist_roster(
        settings.resolve(settings.memory_dir),
        [m.model_dump() for m in req.members],
        today=date.today().isoformat(),
    )
    return {
        "self": next(p.id for p in persisted if p.is_self),
        "members": [
            {"id": p.id, "name": p.name, "isSelf": p.is_self} for p in persisted
        ],
    }


class MemberDataRequest(BaseModel):
    finances: dict = {}
    goals: list[dict] = []
    checks: dict = {}
    supportMonthly: str | None = None


@app.post("/api/onboarding/member-data")
def onboarding_member_data(
    req: MemberDataRequest, x_member_id: str = Header(..., alias="X-Member-Id")
) -> dict:
    """Persist one member's onboarding money/goals slice into their memory files.
    Runs after the roster created the member dir, so the member must exist."""
    _assert_member_exists(x_member_id)
    onboarding_persist.persist_member_data(
        settings.resolve(settings.memory_dir),
        x_member_id,
        req.model_dump(),
        today=date.today().isoformat(),
    )
    return {"saved": True}


@app.post("/api/onboarding/extract-document")
async def onboarding_extract_document(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    x_member_id: str = Header(..., alias="X-Member-Id"),
) -> dict:
    """Read an uploaded statement (CSV/XLSX/PDF) and return the investment
    holdings the model found, for the client to review before saving. Writes
    nothing to memory — only confirmed holdings are saved, via member-data.

    An encrypted PDF (e.g. a CAS) replies 422 with a code so the client can ask
    for the password and retry, rather than failing with a 500."""
    _assert_member_exists(x_member_id)
    data = await file.read()
    try:
        result = await document_extract.extract_holdings(
            _provider, filename=file.filename or "", raw_bytes=data, password=password
        )
    except document_extract.PdfPasswordRequired as e:
        code = "pdf_password_wrong" if e.provided else "pdf_password_required"
        raise HTTPException(status_code=422, detail={"code": code})
    except document_extract.UnsupportedDocument as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "holdings": result.holdings,
        "statement_date": result.statement_date,
        "document_type": result.document_type,
    }


class PortfolioSnapshotRequest(BaseModel):
    holdings: list[dict] = []
    statement_date: str | None = None


@app.post("/api/onboarding/portfolio-snapshot")
def onboarding_portfolio_snapshot(
    req: PortfolioSnapshotRequest, x_member_id: str = Header(..., alias="X-Member-Id")
) -> dict:
    """Save reviewed document holdings as a dated portfolio snapshot, under the
    document's statement date (or today when absent). The live asset register is
    updated separately via member-data; this keeps the dated, itemized history."""
    _assert_member_exists(x_member_id)
    as_of = onboarding_persist.persist_portfolio_snapshot(
        x_member_id,
        req.holdings,
        statement_date=req.statement_date,
        today=date.today().isoformat(),
    )
    return {"saved": True, "as_of": as_of}


class GroupHoldingsRequest(BaseModel):
    sources: list[dict] = []


@app.post("/api/onboarding/group-holdings")
async def onboarding_group_holdings(
    req: GroupHoldingsRequest, x_member_id: str = Header(..., alias="X-Member-Id")
) -> dict:
    """Merge holdings extracted from several statements into one list, collapsing
    overlaps (a CAS already consolidates all mutual funds) so the household total
    is not double-counted. Reads nothing from and writes nothing to memory."""
    _assert_member_exists(x_member_id)
    holdings = await document_extract.group_holdings(_provider, sources=req.sources)
    return {"holdings": holdings}


@app.post("/chat")
async def chat(
    req: ChatRequest,
    x_member_id: str = Header(..., alias="X-Member-Id"),
):
    _assert_member_exists(x_member_id)

    async def event_stream() -> AsyncIterator[dict]:
        # The block below is the ONLY place TurnEvent → SSE mapping exists.
        # SSE event shape is FROZEN — see module docstring.
        async for ev in pipeline.run_chat_turn(
            provider=_provider,
            member=x_member_id,
            user_message=req.message,
            quoted_text=req.quoted_text,
            quoted_role=req.quoted_role or "",
            memory_root=settings.resolve(settings.memory_dir),
            skills_root=settings.resolve(settings.skills_dir),
            max_tokens=settings.max_response_tokens,
        ):
            if isinstance(ev, TurnToken):
                yield {"event": "token", "data": json.dumps({"text": ev.text})}
            elif isinstance(ev, TurnDone):
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {"session_id": ev.session_id, "turn_id": ev.turn_id}
                    ),
                }
            elif isinstance(ev, TurnError):
                yield {"event": "error", "data": json.dumps({"message": ev.message})}
                return

    return EventSourceResponse(event_stream())


@app.post("/session/close", status_code=204)
async def session_close(
    req: SessionCloseRequest,
    x_member_id: str | None = Header(default=None, alias="X-Member-Id"),
) -> Response:
    member = req.member or x_member_id
    if member:
        _validate_member_id(member)
        active_sid = sessions.get_active(member, time.monotonic())
        if active_sid is not None:
            await close_session(member, active_sid)
        sessions.close(member)
    return Response(status_code=204)
