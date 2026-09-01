"""Session lifecycle, account telemetry and autopilot control."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..agents import autopilot
from ..agents.alpaca_mcp import MagnoTools
from ..broker import AlpacaBroker, BrokerError
from ..config import settings
from ..deps import require_session
from ..events import EventCategory
from ..frame import build_frame, drop_cache
from ..quant.risk_gate import RiskEnvelope
from ..state_store import SessionState, Strategy, store

router = APIRouter(prefix="/api", tags=["telemetry"])


class OnboardRequest(BaseModel):
    api_key: str = Field(min_length=8, description="Alpaca **paper** API key ID")
    secret_key: str = Field(min_length=8, description="Alpaca paper secret key")
    strategy: Strategy = Strategy.ADAPTIVE_VRP
    delta_drift_threshold: float = Field(default=1.0, gt=0, le=1000)
    max_spread_pct: float = Field(default=0.05, gt=0, le=0.5)
    max_allocation_pct: float = Field(default=0.10, gt=0, le=1.0)
    max_daily_loss_pct: float = Field(default=0.05, gt=0, le=1.0)
    max_open_positions: int = Field(default=6, ge=1, le=50)
    contract_qty: int = Field(default=1, ge=1, le=50)
    min_dte: float = Field(default=5.0, ge=0, le=400)
    max_dte: float = Field(default=60.0, ge=1, le=800)
    # Volatility policy. Omit to inherit the selected strategy's defaults.
    iv_rank_sell_at: float | None = Field(default=None, ge=0, le=100)
    iv_rank_buy_at: float | None = Field(default=None, ge=0, le=100)


class VerifyRequest(BaseModel):
    api_key: str
    secret_key: str


@router.post("/session/verify")
async def verify_credentials(payload: VerifyRequest) -> dict:
    """Validate keys against the paper endpoint and report the account state.

    Called by onboarding before a session is created, so the operator sees the
    $100k verification result before committing.
    """
    try:
        broker = AlpacaBroker(payload.api_key.strip(), payload.secret_key.strip())
        account = await broker.get_account()
    except BrokerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    target = settings.required_starting_equity
    tolerance = settings.equity_verification_tolerance
    equity_ok = abs(account.equity - target) <= target * tolerance

    warnings: list[str] = []
    if not equity_ok:
        warnings.append(
            f"Account equity is ${account.equity:,.2f}. The hackathon baseline is "
            f"${target:,.0f} — reset your paper account in the Alpaca dashboard if this "
            f"is unexpected. Magno will still run against this balance."
        )
    if account.options_trading_level < 1:
        warnings.append(
            "This paper account has no options approval. Enable options trading "
            "(level 2 or higher recommended) in the Alpaca paper dashboard."
        )
    elif account.options_trading_level < 3:
        warnings.append(
            f"Options level {account.options_trading_level}: long calls/puts are available, "
            "but short-premium legs require level 3."
        )
    if account.trading_blocked:
        warnings.append("Alpaca reports trading_blocked=true on this account.")

    return {
        "valid": True,
        "equity_verified": equity_ok,
        "required_equity": target,
        "account": account.as_dict(),
        "warnings": warnings,
        "endpoint": settings.alpaca_paper_base_url,
    }


@router.post("/session", status_code=status.HTTP_201_CREATED)
async def create_session(payload: OnboardRequest) -> dict:
    """Create an in-memory session. Credentials never leave this process."""
    if payload.min_dte >= payload.max_dte:
        raise HTTPException(status_code=422, detail="min_dte must be less than max_dte.")

    try:
        broker = AlpacaBroker(payload.api_key.strip(), payload.secret_key.strip())
        account = await broker.get_account()
    except BrokerError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Thresholds default to the strategy's own, but the operator's explicit
    # values win. These are policy dials, not agent internals.
    default_sell, default_buy = payload.strategy.thresholds
    sell_at = payload.iv_rank_sell_at if payload.iv_rank_sell_at is not None else default_sell
    buy_at = payload.iv_rank_buy_at if payload.iv_rank_buy_at is not None else default_buy
    if sell_at is not None and buy_at is not None and buy_at >= sell_at:
        raise HTTPException(
            status_code=422,
            detail="iv_rank_buy_at must be below iv_rank_sell_at, or the bands overlap.",
        )

    envelope = RiskEnvelope(
        iv_rank_sell_at=sell_at,
        iv_rank_buy_at=buy_at,
        max_spread_pct=payload.max_spread_pct,
        max_allocation_pct=payload.max_allocation_pct,
        delta_drift_threshold=payload.delta_drift_threshold,
        max_daily_loss_pct=payload.max_daily_loss_pct,
        max_open_positions=payload.max_open_positions,
        min_dte=payload.min_dte,
        max_dte=payload.max_dte,
    )
    state = store.create(broker, account, envelope, payload.strategy, payload.contract_qty)

    state.audit.success(
        EventCategory.SYSTEM,
        "Session established",
        f"Alpaca paper account {account.account_number} · equity ${account.equity:,.2f} · "
        f"options level {account.options_trading_level} · strategy {payload.strategy.label}",
        account_number=account.account_number,
        equity=account.equity,
    )
    state.audit.info(
        EventCategory.RISK,
        "Risk envelope armed",
        f"spread ≤ {envelope.max_spread_pct:.0%} · allocation ≤ "
        f"{envelope.max_allocation_pct:.0%} BP · drift cap ±{envelope.delta_drift_threshold:.2f}Δ · "
        f"loss breaker {envelope.max_daily_loss_pct:.0%} · max {envelope.max_open_positions} positions · "
        f"IV rank buy ≤ {buy_at if buy_at is not None else '—'} / sell ≥ {sell_at if sell_at is not None else '—'}",
        envelope=envelope.as_dict(),
    )

    return {"session_id": state.session_id, "session": state.public_dict(), "account": account.as_dict()}


@router.get("/session")
async def get_session(state: SessionState = Depends(require_session)) -> dict:
    return {"session": state.public_dict(), "account": state.account.as_dict()}


@router.delete("/session")
async def end_session(state: SessionState = Depends(require_session)) -> dict:
    """Tear down the session: cancels the autopilot task and drops the
    credentials from memory."""
    session_id = state.session_id
    drop_cache(session_id)
    await store.drop(session_id)
    return {"ended": True, "session_id": session_id}


@router.get("/telemetry")
async def get_telemetry(state: SessionState = Depends(require_session)) -> dict:
    """One-shot snapshot. The websocket at /ws/telemetry is the live channel."""
    return await build_frame(state, include_events=True)


@router.get("/greeks")
async def get_greeks(state: SessionState = Depends(require_session)) -> dict:
    return await MagnoTools(state).get_account_greeks()


@router.get("/events")
async def get_events(limit: int = 150, state: SessionState = Depends(require_session)) -> dict:
    return {"events": state.audit.recent(min(max(limit, 1), 500))}


class AutopilotRequest(BaseModel):
    enabled: bool


@router.post("/autopilot")
async def set_autopilot(
    payload: AutopilotRequest, state: SessionState = Depends(require_session)
) -> dict:
    if payload.enabled:
        autopilot.start(state)
    else:
        await autopilot.stop(state)
    return {"autopilot": state.autopilot, "session": state.public_dict()}


class EnvelopeUpdate(BaseModel):
    delta_drift_threshold: float | None = Field(default=None, gt=0, le=1000)
    max_spread_pct: float | None = Field(default=None, gt=0, le=0.5)
    max_allocation_pct: float | None = Field(default=None, gt=0, le=1.0)
    max_daily_loss_pct: float | None = Field(default=None, gt=0, le=1.0)
    max_open_positions: int | None = Field(default=None, ge=1, le=50)
    contract_qty: int | None = Field(default=None, ge=1, le=50)
    iv_rank_sell_at: float | None = Field(default=None, ge=0, le=100)
    iv_rank_buy_at: float | None = Field(default=None, ge=0, le=100)


@router.patch("/envelope")
async def update_envelope(
    payload: EnvelopeUpdate, state: SessionState = Depends(require_session)
) -> dict:
    """Retune risk limits without tearing down the session."""
    from dataclasses import replace

    changes = payload.model_dump(exclude_none=True)
    contract_qty = changes.pop("contract_qty", None)
    if changes:
        state.envelope = replace(state.envelope, **changes)
    if contract_qty is not None:
        state.contract_qty = contract_qty

    if changes or contract_qty is not None:
        state.audit.info(
            EventCategory.RISK,
            "Risk envelope updated",
            ", ".join(f"{k}={v}" for k, v in {**changes, "contract_qty": contract_qty}.items() if v is not None),
            envelope=state.envelope.as_dict(),
        )
    return {"envelope": state.envelope.as_dict(), "contract_qty": state.contract_qty}
