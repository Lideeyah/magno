"""In-memory session state.

Alpaca credentials submitted at onboarding live here and nowhere else: they are
never written to disk, never logged, and never returned to the client. A session
dies with the process. That is a deliberate trade-off for a hackathon judging
build -- it keeps the blast radius of the demo to zero.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .broker import AccountSnapshot, AlpacaBroker
from .config import settings
from .events import AuditLog
from .quant.risk_gate import RiskEnvelope


class Strategy(str, Enum):
    """Selectable agent mandates. Each shapes both the LLM prompt and the
    deterministic fallback policy, so behaviour is consistent whether or not the
    model is reachable."""

    DELTA_NEUTRAL_INCOME = "delta_neutral_income"
    LONG_VOL_CONVEXITY = "long_vol_convexity"
    ADAPTIVE_VRP = "adaptive_vrp"

    @property
    def label(self) -> str:
        return {
            Strategy.DELTA_NEUTRAL_INCOME: "Delta-Neutral Income",
            Strategy.LONG_VOL_CONVEXITY: "Long Volatility / Convexity",
            Strategy.ADAPTIVE_VRP: "Adaptive Variance Risk Premium",
        }[self]

    @property
    def thresholds(self) -> tuple[float | None, float | None]:
        """(sell_at_or_above, buy_at_or_below) in IV-rank points.

        Single source of truth for the decision boundary: the LLM prompt and the
        deterministic fallback both read these, so the model can never be given
        a rule the quant policy disagrees with.
        """
        return {
            Strategy.DELTA_NEUTRAL_INCOME: (60.0, None),
            Strategy.LONG_VOL_CONVEXITY: (None, 40.0),
            Strategy.ADAPTIVE_VRP: (65.0, 35.0),
        }[self]

    def signal_for(self, iv_rank: float | None) -> str | None:
        """'sell', 'buy', or None when the rank sits in the neutral band."""
        if iv_rank is None:
            return None
        sell_at, buy_at = self.thresholds
        if sell_at is not None and iv_rank >= sell_at:
            return "sell"
        if buy_at is not None and iv_rank <= buy_at:
            return "buy"
        return None

    @property
    def decision_rule(self) -> str:
        """The mandate stated as arithmetic, for the system prompt.

        The model previously read a prose mandate and talked itself out of
        trades that its own rule required — most memorably holding at IV rank 25
        with implied vol 13.7 points *below* realised, which is the textbook
        long-volatility setup. Numbers are harder to argue with than adjectives.
        """
        sell_at, buy_at = self.thresholds
        clauses = []
        if sell_at is not None:
            clauses.append(f"IV rank >= {sell_at:.0f}  ->  SELL premium (volatility is rich)")
        if buy_at is not None:
            clauses.append(f"IV rank <= {buy_at:.0f}  ->  BUY premium (volatility is cheap)")
        clauses.append("otherwise  ->  HOLD (no measurable edge)")
        return "\n".join(f"  {c}" for c in clauses)

    @property
    def mandate(self) -> str:
        return {
            Strategy.DELTA_NEUTRAL_INCOME: (
                "Harvest the variance risk premium. Prefer selling richly priced premium "
                "when IV rank is elevated, keep every position defined-risk, and hold "
                "portfolio delta at zero via continuous equity hedging."
            ),
            Strategy.LONG_VOL_CONVEXITY: (
                "Buy convexity when volatility is cheap. Prefer long options when IV rank "
                "is depressed relative to realised vol, accept negative theta as the cost "
                "of gamma, and hedge delta so the position expresses vol, not direction."
            ),
            Strategy.ADAPTIVE_VRP: (
                "Trade the spread between implied and realised volatility in both "
                "directions: sell premium when IV rank is high, buy it when IV rank is "
                "low, stand aside in the middle. Always hedge delta to zero."
            ),
        }[self]


@dataclass
class SessionState:
    session_id: str
    broker: AlpacaBroker
    envelope: RiskEnvelope
    strategy: Strategy
    audit: AuditLog
    account: AccountSnapshot
    created_at: datetime

    # Baseline for the daily-loss circuit breaker, captured at onboarding.
    equity_at_open: float = 0.0
    contract_qty: int = 1

    autopilot: bool = False
    autopilot_task: asyncio.Task | None = None

    # Judge-facing shock harness: underlying -> fractional move (0.02 = +2%).
    shocks: dict[str, float] = field(default_factory=dict)

    # Most recent computed telemetry frame, served to late-joining websockets.
    last_frame: dict[str, Any] = field(default_factory=dict)

    # Guards the trade/hedge critical section so a manual order and an autopilot
    # cycle can never double-submit against the same delta reading.
    trade_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Monotonic timestamp of the last "market closed" notice, so the overnight
    # loop does not flood the ledger.
    last_closed_notice_at: float = -1e9

    reasoning_in_flight: bool = False
    last_reasoning_at: datetime | None = None
    cycle_count: int = 0

    def public_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "strategy": self.strategy.value,
            "strategy_label": self.strategy.label,
            "envelope": self.envelope.as_dict(),
            "contract_qty": self.contract_qty,
            "autopilot": self.autopilot,
            "equity_at_open": self.equity_at_open,
            "shocks": self.shocks,
            "cycle_count": self.cycle_count,
            "universe": settings.universe,
            "account_number": self.account.account_number,
            "account_id": self.account.account_id,
            "options_trading_level": self.account.options_trading_level,
            "last_reasoning_at": self.last_reasoning_at.isoformat() if self.last_reasoning_at else None,
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    def create(
        self,
        broker: AlpacaBroker,
        account: AccountSnapshot,
        envelope: RiskEnvelope,
        strategy: Strategy,
        contract_qty: int,
    ) -> SessionState:
        session_id = secrets.token_urlsafe(24)
        state = SessionState(
            session_id=session_id,
            broker=broker,
            envelope=envelope,
            strategy=strategy,
            audit=AuditLog(),
            account=account,
            created_at=datetime.now(timezone.utc),
            equity_at_open=account.last_equity or account.equity,
            contract_qty=contract_qty,
        )
        self._sessions[session_id] = state
        return state

    def get(self, session_id: str | None) -> SessionState | None:
        if not session_id:
            return None
        return self._sessions.get(session_id)

    async def drop(self, session_id: str) -> None:
        state = self._sessions.pop(session_id, None)
        if state and state.autopilot_task and not state.autopilot_task.done():
            state.autopilot_task.cancel()
            try:
                await state.autopilot_task
            except (asyncio.CancelledError, Exception):
                pass

    def all(self) -> list[SessionState]:
        return list(self._sessions.values())


store = SessionStore()
