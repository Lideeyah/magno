"""Manual execution, hedging, and the shock-simulation harness."""

from __future__ import annotations

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
