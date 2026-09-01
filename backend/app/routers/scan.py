"""Volatility scanning and live option chain retrieval."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..agents.alpaca_mcp import MagnoTools
from ..broker import BrokerError
from ..config import settings
from ..deps import require_session
from ..quant.risk_gate import evaluate_option_order
from ..state_store import SessionState

router = APIRouter(prefix="/api", tags=["scan"])


@router.get("/scan")
async def scan(
    underlyings: str | None = Query(default=None, description="Comma-separated tickers"),
    state: SessionState = Depends(require_session),
) -> dict:
    """Run the full scan: IV rank per name plus the gate verdict on every contract."""
    names = [s.strip().upper() for s in underlyings.split(",")] if underlyings else None
    result = await MagnoTools(state).scan_market_volatility(names)
    # The internal object handles are for in-process callers only.
    return {k: v for k, v in result.items() if not k.startswith("_")}


@router.get("/chain/{underlying}")
async def chain(
    underlying: str,
    right: str | None = Query(default=None, pattern="^[CP]$"),
    moneyness_band: float = Query(default=0.12, gt=0, le=0.5),
    state: SessionState = Depends(require_session),
) -> dict:
    """Live chain for one underlying with a gate verdict attached to each row."""
    env = state.envelope
    try:
        rows = await state.broker.get_chain(
            underlying,
            min_dte=env.min_dte,
            max_dte=env.max_dte,
            moneyness_band=moneyness_band,
            right=right,
        )
        account = await state.broker.get_account()
        market_open = await state.broker.is_market_open()
        positions = await state.broker.get_positions()
    except BrokerError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    open_options = sum(1 for p in positions if p.is_option)
    out = []
    for c in rows:
        gate = evaluate_option_order(
            bid=c.bid,
            ask=c.ask,
            iv=c.iv,
            dte=c.dte,
            open_interest=c.open_interest,
            contracts=state.contract_qty,
            buying_power=account.options_buying_power or account.buying_power,
            open_positions=open_options,
            day_pnl=account.day_pnl,
            equity_at_open=state.equity_at_open,
            # Market hours are a property of the clock, not of the contract.
            # Folding them into the per-row verdict makes every row read
            # "rejected" overnight and hides the eight checks that actually
            # discriminate between contracts. The clock is reported once,
            # separately, and the UI disables trading on it.
            market_open=True,
            envelope=env,
        )
        row = c.as_dict()
        row["gate"] = gate.as_dict()
        out.append(row)

    spot = rows[0].spot if rows else None
    return {
        "underlying": underlying.upper(),
        "spot": spot,
        "market_open": market_open,
        "count": len(out),
        # "Contract-clean": passed every check that is a property of the
        # contract. Trading additionally requires the market to be open.
        "approved": sum(1 for r in out if r["gate"]["approved"]),
        "contracts": out,
    }


@router.post("/reason/dry-run")
async def dry_run(state: SessionState = Depends(require_session)) -> dict:
    """Run the full reasoning path — scan, model, gates — without executing.

    Exists so the reasoner is demonstrable outside market hours, when the
    autonomous loop deliberately refuses to spend a model call. No code path
    from here can submit an order.
    """
    return await MagnoTools(state).dry_run_reasoning()


@router.get("/vol-surface")
async def vol_surface(state: SessionState = Depends(require_session)) -> dict:
    """IV rank and realised-vol context for the configured universe."""
    profiles = []
    errors = []
    for name in settings.universe:
        try:
            atm = await state.broker.atm_iv(name)
            profiles.append((await state.broker.get_vol_profile(name, atm)).as_dict())
        except BrokerError as exc:
            errors.append(f"{name}: {exc}")
    return {"profiles": profiles, "errors": errors}
