"""Composition of the 1 Hz telemetry frame served to the terminal.

Alpaca's REST limit is ~200 requests/minute per key. A naive 1 Hz frame that
refetched everything would burn through that with a single browser tab open, so
each component carries its own refresh interval and the frame is assembled from
whatever is current. Account and positions (the numbers that must feel live)
refresh every tick; orders, clock and the volatility surface refresh on longer
intervals behind a cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .agents.alpaca_mcp import build_book
from .broker import BrokerError
from .config import settings
from .state_store import SessionState

log = logging.getLogger("magno.frame")

CLOCK_TTL_S = 30.0
ORDERS_TTL_S = 4.0
VOL_TTL_S = 120.0
# Account and positions are the numbers that must feel live, so they refresh on
# essentially every tick. The TTL sits just under the 1 Hz cadence so a single
# tick still refetches, but *concurrent* readers — a second browser tab, a
# reconnecting socket, the autopilot — coalesce onto one fetch instead of each
# issuing their own. Alpaca allows ~200 requests/minute per key; without this,
# two open tabs alone would exhaust it.
CORE_TTL_S = 0.9


@dataclass
class _FrameCache:
    clock: tuple[float, dict] | None = None
    orders: tuple[float, list[dict]] | None = None
    vol: tuple[float, list[dict]] | None = None
    core: tuple[float, dict, list[dict], dict, bool] | None = None
    core_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    errors: list[str] = field(default_factory=list)


_caches: dict[str, _FrameCache] = {}


def _cache_for(state: SessionState) -> _FrameCache:
    return _caches.setdefault(state.session_id, _FrameCache())


def drop_cache(session_id: str) -> None:
    _caches.pop(session_id, None)


async def _core(
    state: SessionState, cache: _FrameCache
) -> tuple[dict, list[dict], dict, bool]:
    """Account + positions + aggregate Greeks, fetched at most once per tick.

    The lock is what makes concurrent readers share a fetch rather than stampede:
    the first caller does the work, the rest wait and then find the result fresh
    in the cache.
    """
    async with cache.core_lock:
        now = time.monotonic()
        if cache.core and now - cache.core[0] < CORE_TTL_S:
            _, account, positions, greeks, shocked = cache.core
            return account, positions, greeks, shocked

        account: dict[str, Any] = {}
        positions: list[dict] = []
        greeks: dict[str, Any] = {}
        shocked = False

        try:
            account = (await state.broker.get_account()).as_dict()
        except BrokerError as exc:
            cache.errors.append(str(exc))

        try:
            view = await build_book(state)
            positions = [p.as_dict() for p in view.positions]
            greeks = view.book.as_dict()
            shocked = view.shocked
        except BrokerError as exc:
            cache.errors.append(str(exc))

        # Serve the previous frame's values rather than blanking the terminal on
        # a single transient upstream failure.
        if not account and cache.core:
            account = cache.core[1]
        if not greeks and cache.core:
            positions, greeks, shocked = cache.core[2], cache.core[3], cache.core[4]

        cache.core = (now, account, positions, greeks, shocked)
        return account, positions, greeks, shocked


async def _clock(state: SessionState, cache: _FrameCache) -> dict:
    now = time.monotonic()
    if cache.clock and now - cache.clock[0] < CLOCK_TTL_S:
        return cache.clock[1]
    try:
        clock = await state.broker.get_clock()
    except BrokerError as exc:
        cache.errors.append(str(exc))
        return cache.clock[1] if cache.clock else {"is_open": False}
    cache.clock = (now, clock)
    return clock


async def _orders(state: SessionState, cache: _FrameCache) -> list[dict]:
    now = time.monotonic()
    if cache.orders and now - cache.orders[0] < ORDERS_TTL_S:
        return cache.orders[1]
    try:
        orders = await state.broker.get_recent_orders(limit=40)
    except BrokerError as exc:
        cache.errors.append(str(exc))
        return cache.orders[1] if cache.orders else []
    cache.orders = (now, orders)
    return orders


async def _vol_surface(state: SessionState, cache: _FrameCache) -> list[dict]:
    """The volatility surface is expensive (a chain fetch per name), so it
    refreshes on a slow interval and is served stale in between."""
    now = time.monotonic()
    if cache.vol and now - cache.vol[0] < VOL_TTL_S:
        return cache.vol[1]

    async def one(name: str) -> dict | None:
        try:
            atm = await state.broker.atm_iv(name)
            return (await state.broker.get_vol_profile(name, atm)).as_dict()
        except BrokerError as exc:
            cache.errors.append(f"{name}: {exc}")
            return None

    results = await asyncio.gather(*(one(n) for n in settings.universe), return_exceptions=True)
    profiles = [r for r in results if isinstance(r, dict)]
    if profiles:
        cache.vol = (now, profiles)
    return profiles if profiles else (cache.vol[1] if cache.vol else [])


async def build_frame(state: SessionState, *, include_events: bool = False) -> dict[str, Any]:
    """Assemble one telemetry frame. Never raises: a partial frame with an
    ``errors`` array beats a dead websocket."""
    cache = _cache_for(state)
    cache.errors = []

    account, positions, greeks, shocked = await _core(state, cache)

    clock, orders, vol = await asyncio.gather(
        _clock(state, cache), _orders(state, cache), _vol_surface(state, cache)
    )

    threshold = state.envelope.delta_drift_threshold
    net_delta = greeks.get("net_delta", 0.0)
    breach = abs(net_delta) >= threshold

    frame: dict[str, Any] = {
        "type": "telemetry",
        "ts": time.time(),
        "session": state.public_dict(),
        "account": account,
        "positions": positions,
        "greeks": greeks,
        "clock": clock,
        "orders": orders,
        "vol_surface": vol,
        "hedge": {
            "threshold": threshold,
            "net_delta": net_delta,
            "breach": breach,
            "utilisation": (abs(net_delta) / threshold) if threshold else 0.0,
            "shocked": shocked,
            "shocks": dict(state.shocks),
        },
        "errors": cache.errors,
    }
    if include_events:
        frame["events"] = state.audit.recent(150)

    state.last_frame = frame
    return frame
