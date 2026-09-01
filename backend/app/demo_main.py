"""Dedicated backend for the auto-demo sandbox.

A separate ASGI app on its own port, so the demo can boot a session directly
from ``DEMO_ALPACA_*`` credentials without restarting — or otherwise touching —
the production instance on :8000. Nothing here is imported by ``app.main``.

    uvicorn app.demo_main:app --port 8001

It mounts the same routers, so the demo renders identical telemetry, and adds
one unauthenticated endpoint the browser can call to discover the session id
that was minted at startup. That removes the manual handoff entirely: the demo
page loads and is already connected.

The session it creates is independent of any session on :8000. Two sessions
against the same Alpaca account read the same book but hold separate risk
envelopes and separate autopilot state, so a demo can never arm or disarm the
instance you are trading.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .broker import AlpacaBroker, BrokerError
from .config import settings
from .events import EventCategory
from .quant.risk_gate import RiskEnvelope
from .routers import orders, scan, telemetry
from .state_store import Strategy, store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("magno.demo")

# Populated at startup from DEMO_ALPACA_* credentials.
_demo: dict[str, str | None] = {"session_id": None, "error": None}


async def _mint_demo_session() -> None:
    """Create the demo's own session from environment credentials."""
    if not settings.demo_alpaca_api_key or not settings.demo_alpaca_secret_key:
        _demo["error"] = (
            "DEMO_ALPACA_API_KEY and DEMO_ALPACA_SECRET_KEY are not set. "
            "Copy frontend/.env.demo.example to backend/.env.demo and fill them in, "
            "or export them before starting this server."
        )
        log.warning(_demo["error"])
        return

    try:
        broker = AlpacaBroker(
            settings.demo_alpaca_api_key, settings.demo_alpaca_secret_key
        )
        account = await broker.get_account()
    except BrokerError as exc:
        _demo["error"] = str(exc)
        log.error("demo session could not be created: %s", exc)
        return

    state = store.create(
        broker,
        account,
        RiskEnvelope(),
        Strategy.ADAPTIVE_VRP,
        settings.default_contract_qty,
    )
    _demo["session_id"] = state.session_id
    _demo["error"] = None

    state.audit.success(
        EventCategory.SYSTEM,
        "Demo session established",
        f"Alpaca paper account {account.account_number} · equity ${account.equity:,.2f}. "
        f"Read-only demo sandbox; autopilot is not engaged.",
        account_number=account.account_number,
    )
    log.info(
        "demo session ready · account %s · equity $%.2f",
        account.account_number,
        account.equity,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Magno DEMO backend starting on port %s", settings.demo_backend_port)
    await _mint_demo_session()
    yield
    sid = _demo.get("session_id")
    if sid:
        await store.drop(sid)
    log.info("Magno DEMO backend shut down")


app = FastAPI(
    title="Magno — demo sandbox",
    version="1.0.0",
    description=(
        "Isolated backend for the 120-second auto-demo. Boots its own Alpaca "
        "session from DEMO_ALPACA_* credentials. Separate process and port from "
        "the production instance."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(telemetry.router)
app.include_router(scan.router)
app.include_router(orders.router)


@app.get("/api/demo/session", tags=["demo"])
async def demo_session() -> dict:
    """The session minted at startup, so the browser needs no manual handoff."""
    if _demo["error"]:
        return {"ready": False, "error": _demo["error"]}
    if not _demo["session_id"]:
        return {"ready": False, "error": "Demo session not initialised."}

    state = store.get(_demo["session_id"])
    if state is None:
        return {"ready": False, "error": "Demo session expired."}
    return {
        "ready": True,
        "session_id": state.session_id,
        "account_number": state.account.account_number,
        "equity_at_open": state.equity_at_open,
    }


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": "magno-demo",
        "demo_session_ready": bool(_demo["session_id"]),
        "error": _demo["error"],
        "paper_endpoint": settings.demo_alpaca_base_url,
        "reasoner": {
            "provider": "featherless" if settings.demo_featherless_api_key or settings.featherless_api_key else "deterministic",
        },
    }


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})
