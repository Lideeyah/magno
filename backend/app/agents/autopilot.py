"""The autonomous loop.

Two cadences run inside one task so they can share a lock and never race:

* **Hedge cadence** (default 5s) -- recompute portfolio delta and neutralise any
  underlying past the drift cap. This is deterministic and runs on every tick.
* **Reasoning cadence** (default 60s) -- scan the universe, ask the model for a
  decision, and route an approved decision through the gate chain to execution.

The hedge cadence is the fast one on purpose. Risk correction must not wait on
model latency, and if the reasoner is down the book still stays neutral.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ..config import settings
from ..events import EventCategory, EventLevel
from ..state_store import SessionState
from . import reasoner
from .alpaca_mcp import MagnoTools, build_book

log = logging.getLogger("magno.autopilot")

# Exponential backoff bounds for upstream failures, so a broker outage produces
# a slow retry rather than a hot loop against a rate limiter.
BACKOFF_MIN_S = 5.0
BACKOFF_MAX_S = 120.0
# How often the loop restates that the market is shut. Frequent enough to prove
# it is alive, rare enough not to flood the ledger overnight.
CLOSED_NOTICE_INTERVAL_S = 900.0


async def run_autopilot(state: SessionState) -> None:
    tools = MagnoTools(state)
    audit = state.audit

    audit.success(
        EventCategory.SYSTEM,
        "Autopilot engaged",
        f"{state.strategy.label} · hedge every {settings.hedge_interval_s:.0f}s · "
        f"reason every {settings.reasoning_interval_s:.0f}s · "
        f"drift cap ±{state.envelope.delta_drift_threshold:.2f}Δ",
        strategy=state.strategy.value,
        envelope=state.envelope.as_dict(),
    )

    last_reason = 0.0
    backoff = 0.0

    try:
        while True:
            loop_started = asyncio.get_event_loop().time()
            try:
                await _exit_tick(state, tools)
                await _hedge_tick(state, tools)

                if loop_started - last_reason >= settings.reasoning_interval_s:
                    last_reason = loop_started
                    await _reasoning_tick(state, tools)

                backoff = 0.0
                state.cycle_count += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                backoff = min(max(backoff * 2, BACKOFF_MIN_S), BACKOFF_MAX_S)
                log.exception("autopilot cycle failed")
                audit.error(
                    EventCategory.SYSTEM,
                    "Autopilot cycle error",
                    f"{type(exc).__name__}: {exc} — retrying in {backoff:.0f}s",
                )
                await asyncio.sleep(backoff)
                continue

            elapsed = asyncio.get_event_loop().time() - loop_started
            await asyncio.sleep(max(0.5, settings.hedge_interval_s - elapsed))

    except asyncio.CancelledError:
        audit.warn(EventCategory.SYSTEM, "Autopilot disengaged", "Operator stopped the agent.")
        raise


async def _exit_tick(state: SessionState, tools: MagnoTools) -> None:
    """Take profits, cut losses, and stand down before expiry.

    Runs ahead of the hedge on every cycle and is exempt from the daily-loss
    breaker. A breaker that stops an agent closing a losing position during a
    drawdown makes the drawdown worse — it must only stop *new* risk.
    """
    async with state.trade_lock:
        result = await tools.close_expiring_and_triggered()
    if result.get("closed"):
        state.audit.info(
            EventCategory.ORDER,
            "Exit cycle complete",
            f"{result['closed']} position(s) closed on profit, stop or time.",
        )


async def _hedge_tick(state: SessionState, tools: MagnoTools) -> None:
    """Deterministic risk correction. No model in this path."""
    async with state.trade_lock:
        result = await tools.rebalance_portfolio()
    if result.get("hedged"):
        state.audit.info(
            EventCategory.HEDGE,
            "Rebalance cycle complete",
            f"Net δ was {result['net_delta']:+.3f}; corrective orders submitted.",
        )


async def _reasoning_tick(state: SessionState, tools: MagnoTools) -> None:
    audit = state.audit

    if state.reasoning_in_flight:
        return

    account = await state.broker.get_account()
    market_open = await state.broker.is_market_open()
    if not market_open:
        # The loop keeps running overnight so it trades the moment the bell
        # rings, but saying so every 60s would bury the ledger under hundreds of
        # identical rows. Once every 15 minutes is enough to show it is alive.
        now = asyncio.get_event_loop().time()
        if now - state.last_closed_notice_at >= CLOSED_NOTICE_INTERVAL_S:
            state.last_closed_notice_at = now
            detail = "Holding flat; the hedge loop stays armed and trading resumes at the open."
            try:
                clock = await state.broker.get_clock()
                detail = f"{detail} Next open {clock['next_open']}."
            except Exception:
                pass
            audit.info(EventCategory.SYSTEM, "Market closed", detail)
        return

    # Respect the circuit breaker before spending a model call on a decision we
    # would refuse to act on anyway.
    loss_pct = -account.day_pnl / state.equity_at_open if state.equity_at_open else 0.0
    if loss_pct >= state.envelope.max_daily_loss_pct:
        audit.reject(
            EventCategory.RISK,
            "Daily loss breaker tripped",
            f"Day P&L ${account.day_pnl:,.2f} ({loss_pct:.2%}) at or past the "
            f"{state.envelope.max_daily_loss_pct:.0%} limit. No new risk today; "
            f"delta hedging continues.",
            day_pnl=account.day_pnl,
            loss_pct=loss_pct,
        )
        return

    state.reasoning_in_flight = True
    try:
        scan = await tools.scan_market_volatility()
        candidates = scan["_approved_objects"]
        profiles = scan["_profile_objects"]

        if not candidates:
            audit.info(
                EventCategory.REASONING,
                "No gate-approved candidates",
                "Every contract in the universe failed at least one pre-trade gate this cycle.",
            )
            return

        view = await build_book(state)
        decision = await reasoner.reason(
            strategy=state.strategy,
            envelope=state.envelope,
            vol_profiles=profiles,
            candidates=candidates,
            net_delta=view.book.net_delta,
            open_positions=view.book.gross_option_positions,
            max_positions=state.envelope.max_open_positions,
            buying_power=account.options_buying_power or account.buying_power,
            day_pnl=account.day_pnl,
            max_contracts=state.contract_qty,
        )
        state.last_reasoning_at = datetime.now(timezone.utc)

        for warning in decision.warnings:
            audit.warn(EventCategory.REASONING, "Reasoner warning", warning)

        # A model that only ever echoes the quant policy adds nothing; one that
        # departs from it must be visible when it does.
        if decision.diverged:
            audit.warn(
                EventCategory.REASONING,
                "Model diverged from the quant baseline",
                decision.divergence or "",
                decision=decision.as_dict(),
            )

        origin = (
            f"{decision.source}"
            + (f" · {decision.model}" if decision.model else "")
            + (f" · {decision.latency_ms}ms" if decision.latency_ms else "")
        )

        if decision.action == "HOLD":
            audit.emit(
                EventCategory.REASONING,
                EventLevel.INFO,
                "Decision: HOLD",
                decision.thesis,
                origin=origin,
                decision=decision.as_dict(),
            )
            return

        audit.emit(
            EventCategory.REASONING,
            EventLevel.INFO,
            f"Decision: {decision.side.upper()} {decision.contracts}x {decision.symbol}",
            decision.thesis,
            origin=origin,
            confidence=decision.confidence,
            decision=decision.as_dict(),
        )

        chosen = next((c for c in candidates if c.symbol == decision.symbol), None)
        async with state.trade_lock:
            if decision.side == "sell":
                # A naked short has unbounded loss, which contradicts the
                # defined-risk mandate. Sell signals are expressed as credit
                # verticals; if no wing is quotable the agent stands down rather
                # than selling naked.
                await tools.execute_vertical_spread(
                    short_symbol=decision.symbol or "",
                    contracts=decision.contracts,
                    thesis=decision.thesis,
                )
            else:
                await tools.execute_options_strategy(
                    symbol=decision.symbol or "",
                    side=decision.side,
                    contracts=decision.contracts,
                    thesis=decision.thesis,
                    contract=chosen,
                )
            # Opening a position moves delta immediately; correct it now rather
            # than carrying naked exposure until the next hedge tick.
            await tools.rebalance_portfolio()
    finally:
        state.reasoning_in_flight = False


def start(state: SessionState) -> None:
    if state.autopilot_task and not state.autopilot_task.done():
        return
    state.autopilot = True
    state.autopilot_task = asyncio.create_task(run_autopilot(state))


async def stop(state: SessionState) -> None:
    state.autopilot = False
    task = state.autopilot_task
    state.autopilot_task = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
