"""Manual execution, hedging, and the shock-simulation harness."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ..agents.alpaca_mcp import MagnoTools, build_book
from ..broker import BrokerError
from ..config import settings
from ..deps import require_session
from ..events import EventCategory
from ..quant.hedge_engine import aggregate_portfolio, apply_price_shock, compute_hedge_intents
from ..state_store import SessionState

router = APIRouter(prefix="/api", tags=["orders"])


class OptionOrderRequest(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    contracts: int = Field(default=1, ge=1, le=50)
    thesis: str = ""

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()


@router.post("/orders/option")
async def submit_option(
    payload: OptionOrderRequest, state: SessionState = Depends(require_session)
) -> dict:
    """Operator-initiated options order. Runs the identical gate chain the
    autonomous loop uses -- a manual trade gets no privileges."""
    async with state.trade_lock:
        result = await MagnoTools(state).execute_options_strategy(
            symbol=payload.symbol,
            side=payload.side,
            contracts=payload.contracts,
            thesis=payload.thesis or "Operator-initiated from the terminal.",
            force=True,
        )
    if not result.get("submitted"):
        raise HTTPException(status_code=422, detail=result)
    return result


class HedgeRequest(BaseModel):
    force: bool = False


@router.post("/orders/hedge")
async def hedge(payload: HedgeRequest, state: SessionState = Depends(require_session)) -> dict:
    async with state.trade_lock:
        return await MagnoTools(state).rebalance_portfolio(force=payload.force)


@router.get("/orders")
async def list_orders(limit: int = 50, state: SessionState = Depends(require_session)) -> dict:
    try:
        return {"orders": await state.broker.get_recent_orders(limit=min(max(limit, 1), 200))}
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/diagnostics/preflight")
async def preflight(state: SessionState = Depends(require_session)) -> dict:
    """Probe the live order path with three tiny orders, then cancel them.

    Every normal path is gated on market hours, so outside 09:30–16:00 ET an
    order is stopped by Magno's own gate and never reaches Alpaca. That proves
    the gate works and proves nothing about the broker. This deliberately
    bypasses *only* the market-hours check so the submission path can be
    verified before the open rather than discovered during it.

    Three probes, each ~$8 of notional:

    1. Fractional equity BUY  — expected to be accepted (fractional long).
    2. Fractional equity SELL — expected to be REJECTED. Alpaca does not permit
       fractional short sales, and this is the empirical confirmation of the
       constraint the hedge engine is built around.
    3. Options order — establishes what the broker actually does with an
       options order outside trading hours.

    Anything that rests is cancelled immediately. Nothing here can open a
    meaningful position: sizes are the smallest that clear Alpaca's $1 notional
    floor.
    """
    audit = state.audit
    audit.warn(
        EventCategory.SYSTEM,
        "Preflight started",
        "Probing the live Alpaca order path with cancellable test orders.",
    )

    def _pid(tag: str) -> str:
        return f"magno-pre-{tag}-{datetime.now(timezone.utc):%H%M%S}-{secrets.token_hex(2)}"

    probes: list[dict] = []
    submitted_ids: list[str] = []

    async def probe(name: str, expectation: str, coro) -> None:
        try:
            order = await coro
            if order.get("id"):
                submitted_ids.append(order["id"])
            probes.append(
                {
                    "probe": name,
                    "expectation": expectation,
                    "accepted": True,
                    "status": order.get("status"),
                    "order_id": order.get("id"),
                    "qty": order.get("qty"),
                }
            )
        except BrokerError as exc:
            probes.append(
                {
                    "probe": name,
                    "expectation": expectation,
                    "accepted": False,
                    "error": str(exc),
                }
            )

    spot = (await state.broker.get_spots(["SPY"])).get("SPY") or 0.0
    # Smallest quantity that clears Alpaca's $1 minimum notional, with headroom.
    qty = round(max(0.01, 2.0 / spot), 3) if spot else 0.01

    async def settle(index: int) -> None:
        """Poll a probe order until it resolves. `accepted` is not an answer."""
        entry = probes[index]
        if not entry.get("accepted") or not entry.get("order_id"):
            return
        entry["settled_status"] = "still resting after 10s"
        for _ in range(10):
            await asyncio.sleep(1.0)
            try:
                current = next(
                    (o for o in await state.broker.get_recent_orders(limit=30)
                     if o["id"] == entry["order_id"]),
                    None,
                )
            except BrokerError:
                return
            if current and str(current.get("status", "")).lower() not in (
                "pending_new", "new", "accepted"
            ):
                entry["settled_status"] = current.get("status")
                entry["settled_filled_qty"] = current.get("filled_qty")
                return

    async def spy_equity_qty() -> float:
        for pos in await state.broker.get_positions():
            if pos.symbol.upper() == "SPY" and not pos.is_option:
                return pos.qty
        return 0.0

    # --- 1. Fractional SHORT, from a flat book -------------------------------
    # Order matters. A previous run bought first, so the subsequent sell may
    # have been closing that long rather than opening a short -- which left the
    # question unanswered. Selling first, from flat, makes a resulting negative
    # position unambiguous proof.
    starting_qty = await spy_equity_qty()
    await probe(
        "fractional_equity_short_sell",
        "unknown — a resulting negative position is the only proof",
        state.broker.submit_equity_order("SPY", qty, "sell", client_order_id=_pid("s")),
    )
    await settle(len(probes) - 1)
    after_short = await spy_equity_qty()
    probes[-1]["position_before"] = starting_qty
    probes[-1]["position_after"] = after_short
    probes[-1]["genuine_short"] = after_short < starting_qty and after_short < 0

    # --- 2. Fractional BUY, which also flattens the short above --------------
    await probe(
        "fractional_equity_buy",
        "accepted — fractional long is permitted",
        state.broker.submit_equity_order("SPY", qty, "buy", client_order_id=_pid("b")),
    )
    await settle(len(probes) - 1)

    # A market buy cannot be made unfillable, so this one genuinely executes and
    # must be unwound explicitly. Closing a fractional *long* is permitted --
    # only opening a fractional short is not -- so this always flattens.
    if await spy_equity_qty() > 0:
        try:
            unwind = await state.broker.close_position("SPY")
            probes[-1]["unwound"] = unwind.get("id")
        except BrokerError as exc:
            probes[-1]["unwind_error"] = str(exc)
        for _ in range(8):
            await asyncio.sleep(1.0)
            if abs(await spy_equity_qty()) < 1e-6:
                break

    # --- 3. Options order ----------------------------------------------------
    # Deliberately far below the bid so it rests and is cancelled. An earlier
    # version priced this marketable, so it filled instantly and cancellation
    # was a no-op -- leaving two unwanted 7 DTE calls on the account.
    option_symbol = None
    try:
        chain = await state.broker.get_chain("SPY", min_dte=5, max_dte=60, moneyness_band=0.05)
        quotable = [c for c in chain if c.bid and c.ask and c.mid and c.mid < 8.0]
        if quotable:
            pick = min(quotable, key=lambda c: abs(c.moneyness))
            option_symbol = pick.symbol
            from ..broker import round_to_tick

            unfillable = round_to_tick(max(0.01, pick.bid * 0.5), up=False)
            await probe(
                "option_order_unfillable_limit",
                "accepted and left resting — must not fill",
                state.broker.submit_option_order(
                    pick.symbol, 1, "buy", limit_price=unfillable,
                    client_order_id=_pid("o"),
                ),
            )
    except BrokerError as exc:
        probes.append({"probe": "option_order_unfillable_limit", "accepted": False, "error": str(exc)})

    # --- 4. Multi-leg vertical ----------------------------------------------
    try:
        from ..quant.spreads import build_vertical

        chain = await state.broker.get_chain("SPY", min_dte=5, max_dte=60, moneyness_band=0.08)
        short_pick = next(
            (c for c in sorted(chain, key=lambda c: abs(c.moneyness))
             if c.right == "C" and c.bid and c.ask and c.mid),
            None,
        )
        spread = build_vertical(short_pick, chain, contracts=1) if short_pick else None
        if spread is None or spread.net_credit is None:
            probes.append({
                "probe": "multi_leg_vertical", "accepted": False,
                "error": "Could not assemble a quotable vertical to probe with.",
            })
        else:
            # Demand far more credit than the structure is worth, so it rests.
            unfillable = round((spread.net_credit + spread.width) * 2, 2)
            await probe(
                "multi_leg_vertical",
                "accepted and left resting — position_intent must be inferred",
                state.broker.submit_vertical_spread(
                    short_symbol=spread.short_leg.symbol,
                    long_symbol=spread.long_leg.symbol,
                    qty=1, limit_credit=unfillable, client_order_id=_pid("m"),
                ),
            )
            probes[-1]["structure"] = spread.as_dict()
    except BrokerError as exc:
        probes.append({"probe": "multi_leg_vertical", "accepted": False, "error": str(exc)})

    # Clean up anything that rested.
    cancelled = []
    for order_id in submitted_ids:
        try:
            await state.broker.cancel_order(order_id)
            cancelled.append(order_id)
        except BrokerError as exc:
            cancelled.append(f"{order_id}: FAILED — {exc}")

    audit.warn(
        EventCategory.SYSTEM,
        "Preflight complete",
        f"{sum(1 for p in probes if p['accepted'])}/{len(probes)} probes accepted; "
        f"{len(cancelled)} order(s) cancelled.",
        probes=probes,
    )
    residual = await spy_equity_qty()
    residual_options = [
        p.symbol for p in await state.broker.get_positions()
        if p.is_option and p.underlying == "SPY"
    ]
    return {
        "spot": spot,
        "probe_qty": qty,
        "residual_spy_shares": residual,
        "residual_spy_options": residual_options,
        "clean": abs(residual) < 1e-6 and not residual_options,
        "option_symbol": option_symbol,
        "probes": probes,
        "cancelled": cancelled,
    }


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str, state: SessionState = Depends(require_session)) -> dict:
    """Cancel one resting order."""
    try:
        await state.broker.cancel_order(order_id)
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    state.audit.warn(
        EventCategory.ORDER, "Order cancelled", f"Operator cancelled {order_id}.", order_id=order_id
    )
    return {"cancelled": True, "order_id": order_id}


@router.delete("/orders")
async def cancel_all_orders(state: SessionState = Depends(require_session)) -> dict:
    """Cancel every open order. Leaves positions untouched."""
    try:
        count = await state.broker.cancel_all_orders()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    state.audit.warn(
        EventCategory.ORDER, "All orders cancelled", f"{count} open order(s) cancelled.", count=count
    )
    return {"cancelled": count}


@router.post("/positions/{symbol}/close")
async def close_position(symbol: str, state: SessionState = Depends(require_session)) -> dict:
    try:
        async with state.trade_lock:
            order = await state.broker.close_position(symbol)
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    state.audit.warn(
        EventCategory.ORDER, f"Position closed — {symbol.upper()}", "Operator-initiated close.", order=order
    )
    return {"order": order}


# --------------------------------------------------------------------------- #
# Shock simulation
# --------------------------------------------------------------------------- #
class ShockRequest(BaseModel):
    underlying: str
    pct: float = Field(ge=-0.5, le=0.5, description="Fractional move; 0.02 = +2%")

    @field_validator("underlying")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()


@router.post("/simulate/shock")
async def apply_shock(payload: ShockRequest, state: SessionState = Depends(require_session)) -> dict:
    """Inject a hypothetical underlying move.

    The book is re-priced through Black-Scholes at the shocked spot with implied
    vol held constant, so the delta drift that appears is the genuine gamma
    effect. While a shock is active the hedge engine computes and logs the
    corrective order but does **not** submit it -- the move did not really
    happen, and a real order against a simulated price would corrupt the P&L
    the agent is judged on.
    """
    state.shocks[payload.underlying] = payload.pct

    positions = await state.broker.get_positions()
    spots = await state.broker.get_spots(sorted({p.underlying for p in positions} | set(settings.universe)))
    account = await state.broker.get_account()
    before = aggregate_portfolio(positions, spots)
    shocked_positions, shocked_spots = apply_price_shock(
        positions, state.shocks, spots, settings.risk_free_rate
    )
    after = aggregate_portfolio(shocked_positions, shocked_spots)
    # Gate the hypothetical against real buying power, and assume open hours:
    # the question this answers is "what would the engine do about this move",
    # which is not interesting if the answer is always "nothing, it's 3am".
    intents = compute_hedge_intents(
        after, state.envelope, buying_power=account.buying_power, market_open=True
    )

    state.audit.warn(
        EventCategory.SHOCK,
        f"Shock injected — {payload.underlying} {payload.pct:+.1%}",
        f"Net δ {before.net_delta:+.3f} → {after.net_delta:+.3f} "
        f"({len(intents)} underlying(s) past the ±{state.envelope.delta_drift_threshold:.2f} drift cap)",
        underlying=payload.underlying,
        pct=payload.pct,
        delta_before=before.net_delta,
        delta_after=after.net_delta,
        intents=[i.as_dict() for i in intents],
    )

    return {
        "shocks": dict(state.shocks),
        "delta_before": before.net_delta,
        "delta_after": after.net_delta,
        "greeks_before": before.as_dict(),
        "greeks_after": after.as_dict(),
        "intents": [i.as_dict() for i in intents],
    }


@router.delete("/simulate/shock")
async def clear_shocks(state: SessionState = Depends(require_session)) -> dict:
    had = dict(state.shocks)
    state.shocks.clear()
    if had:
        state.audit.info(
            EventCategory.SHOCK, "Shocks cleared", "Book re-marked to live prices.", cleared=had
        )
    return {"shocks": {}, "cleared": had}


@router.get("/simulate/shock")
async def get_shocks(state: SessionState = Depends(require_session)) -> dict:
    view = await build_book(state)
    return {
        "shocks": dict(state.shocks),
        "net_delta": view.book.net_delta,
        "greeks": view.book.as_dict(),
    }
