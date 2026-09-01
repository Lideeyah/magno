"""Magno FastAPI application and telemetry websocket."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .frame import build_frame, drop_cache
from .routers import orders, scan, telemetry
from .state_store import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("magno")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Magno backend online · universe=%s", ",".join(settings.universe))
    log.info(
        "Reasoner: %s",
        f"Featherless {settings.featherless_model}"
        if settings.featherless_api_key
        else "deterministic quant policy (no FEATHERLESS_API_KEY set)",
    )
    yield
    # Cancel every autopilot task so the process exits cleanly.
    for state in store.all():
        drop_cache(state.session_id)
        await store.drop(state.session_id)
    log.info("Magno backend shut down")


app = FastAPI(
    title="Magno",
    version="1.0.0",
    description=(
        "Autonomous options trading and delta-neutral hedging on Alpaca paper trading. "
        "LLM reasoning proposes; deterministic risk gates dispose."
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


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": "magno",
        "paper_endpoint": settings.alpaca_paper_base_url,
        "universe": settings.universe,
        "reasoner": {
            "provider": "featherless" if settings.featherless_api_key else "deterministic",
            "model": settings.featherless_model if settings.featherless_api_key else None,
            "base_url": settings.featherless_base_url,
            "anthropic_fallback": bool(settings.anthropic_api_key),
        },
        "defaults": {
            "max_spread_pct": settings.max_spread_pct,
            "max_allocation_pct": settings.max_allocation_pct,
            "delta_drift_threshold": settings.delta_drift_threshold,
            "max_daily_loss_pct": settings.max_daily_loss_pct,
        },
        "active_sessions": len(store.all()),
    }


@app.exception_handler(Exception)
async def unhandled(request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


@app.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket, session_id: str = Query(...)) -> None:
    """Live terminal channel.

    Emits a full ``telemetry`` frame on a fixed cadence and pushes ``event``
    messages the instant the agent logs a decision, so the execution stream is
    genuinely real-time rather than polled at the frame rate.
    """
    state = store.get(session_id)
    if state is None:
        # Accept first, then close with the application code. Closing before
        # accept() makes Starlette reject the handshake with HTTP 403, which the
        # browser surfaces as an abnormal 1006 — the client would then treat an
        # expired session as a transient drop and reconnect forever.
        await websocket.accept()
        await websocket.send_json(
            {"type": "error", "code": 4401, "detail": "Unknown or expired session."}
        )
        await websocket.close(code=4401, reason="Unknown or expired session")
        return

    await websocket.accept()
    queue = state.audit.subscribe()
    loop = asyncio.get_event_loop()
    interval = settings.telemetry_interval_s

    try:
        await websocket.send_json(await build_frame(state, include_events=True))
        last_frame_at = loop.time()

        while True:
            now = loop.time()
            if now - last_frame_at >= interval:
                await websocket.send_json(await build_frame(state))
                last_frame_at = loop.time()

            timeout = max(0.05, interval - (loop.time() - last_frame_at))
            try:
                event = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                continue
            await websocket.send_json({"type": "event", "event": event.as_dict()})

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("telemetry websocket failed for session %s", session_id[:8])
    finally:
        state.audit.unsubscribe(queue)
