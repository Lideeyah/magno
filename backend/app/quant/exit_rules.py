"""Exit rules.

The agent could previously open a position and hedge it forever. It had no
concept of taking a profit, cutting a loss, or standing down before expiry —
positions simply decayed into expiry and were assigned. For a book judged on
P&L that is the single largest hole: a long-volatility position bleeding theta
with no exit is a slow loss by construction.

These are the standard premium-selling exit envelopes, expressed as pure
functions over a position so they can be reasoned about and tested without a
broker.

The asymmetry between long and short premium is the thing to get right:

* **Long premium** (a debit was paid) can lose at most 100% — the option
  expires worthless. A "-100% stop" is therefore not a stop at all, it is a
  description of doing nothing. Longs cut at a fraction of the debit instead.
* **Short premium** (a credit was received) has unbounded loss. The convention
  is to close once the loss equals the credit received, i.e. the option has
  roughly doubled in price.

Time is the third axis and applies to both: gamma goes non-linear in the last
few weeks, and assignment mechanics start to matter, so positions are closed
well before expiry regardless of P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .hedge_engine import OPTION_MULTIPLIER, PositionSnapshot


@dataclass(frozen=True)
class ExitTrigger:
    code: str
    message: str
    observed: float | None = None
    limit: float | None = None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "observed": self.observed,
            "limit": self.limit,
        }


@dataclass
class ExitDecision:
    """Why a position should or should not be closed."""

    symbol: str
    should_close: bool
    triggers: list[ExitTrigger] = field(default_factory=list)
    pnl_pct: float = 0.0
    is_short: bool = False
    dte: float | None = None

    @property
    def summary(self) -> str:
        if not self.should_close:
            return "no exit condition met"
        return "; ".join(t.message for t in self.triggers)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "should_close": self.should_close,
            "summary": self.summary,
            "pnl_pct": self.pnl_pct,
            "is_short": self.is_short,
            "dte": self.dte,
            "triggers": [t.as_dict() for t in self.triggers],
        }


@dataclass(frozen=True)
class ExitPolicy:
    """Operator-tunable exit envelope.

    Defaults are the conventional premium-selling rules: take half the maximum
    profit, cut a short at one times the credit received, and never carry a
    position inside three weeks of expiry.
    """

    # Fraction of the entry premium captured before closing a winner.
    take_profit_pct: float = 0.50
    # Short premium: close once the loss reaches this multiple of the credit.
    short_stop_loss_pct: float = 1.00
    # Long premium: close once this fraction of the debit has been lost. A long
    # cannot lose more than 100%, so the stop must sit below that to mean
    # anything.
    long_stop_loss_pct: float = 0.50
    # Close regardless of P&L at or below this many days to expiry.
    time_stop_dte: float = 21.0

    def as_dict(self) -> dict:
        return {
            "take_profit_pct": self.take_profit_pct,
            "short_stop_loss_pct": self.short_stop_loss_pct,
            "long_stop_loss_pct": self.long_stop_loss_pct,
            "time_stop_dte": self.time_stop_dte,
        }


def position_pnl_pct(position: PositionSnapshot) -> float | None:
    """P&L as a fraction of the premium originally paid or received.

    Positive means the position has made money, for both longs and shorts. This
    sign convention is what lets one take-profit threshold serve both.
    """
    entry = abs(position.avg_entry_price)
    if entry <= 0:
        return None

    move = position.current_price - position.avg_entry_price
    # A short position profits as the premium falls, so the sign flips with qty.
    direction = 1.0 if position.qty > 0 else -1.0
    return (move * direction) / entry


def evaluate_exit(
    position: PositionSnapshot, policy: ExitPolicy | None = None
) -> ExitDecision:
    """Decide whether a single option position should be closed.

    Equity legs are never closed by this: they are hedges, and the hedge engine
    owns their size. Closing one here would knock the book directional.
    """
    policy = policy or ExitPolicy()
    decision = ExitDecision(symbol=position.symbol, should_close=False)

    if not position.is_option or position.qty == 0:
        return decision

    decision.is_short = position.qty < 0
    decision.dte = position.dte

    pnl_pct = position_pnl_pct(position)
    if pnl_pct is None:
        # No usable entry price — leave it to the operator rather than guessing.
        return decision
    decision.pnl_pct = pnl_pct

    # --- Take profit ---------------------------------------------------- #
    if pnl_pct >= policy.take_profit_pct:
        decision.triggers.append(
            ExitTrigger(
                "TAKE_PROFIT",
                f"Captured {pnl_pct:.0%} of premium, target {policy.take_profit_pct:.0%}",
                observed=pnl_pct,
                limit=policy.take_profit_pct,
            )
        )

    # --- Stop loss ------------------------------------------------------ #
    stop = policy.short_stop_loss_pct if decision.is_short else policy.long_stop_loss_pct
    if pnl_pct <= -stop:
        label = "credit received" if decision.is_short else "debit paid"
        decision.triggers.append(
            ExitTrigger(
                "STOP_LOSS",
                f"Down {abs(pnl_pct):.0%} of {label}, stop at {stop:.0%}",
                observed=pnl_pct,
                limit=-stop,
            )
        )

    # --- Time stop ------------------------------------------------------ #
    if position.dte is not None and position.dte <= policy.time_stop_dte:
        decision.triggers.append(
            ExitTrigger(
                "TIME_STOP",
                f"{position.dte:.1f} DTE at or inside the {policy.time_stop_dte:.0f}d "
                f"limit; gamma and assignment risk rise sharply from here",
                observed=position.dte,
                limit=policy.time_stop_dte,
            )
        )

    decision.should_close = bool(decision.triggers)
    return decision


def evaluate_exits(
    positions: list[PositionSnapshot], policy: ExitPolicy | None = None
) -> list[ExitDecision]:
    """Exit decisions for every option leg, worst-first.

    Ordering matters when buying power is tight: a stop-loss should be acted on
    before a take-profit, because the losing position is the one that grows.
    """
    decisions = [
        evaluate_exit(p, policy) for p in positions if p.is_option and p.qty != 0
    ]
    closable = [d for d in decisions if d.should_close]
    closable.sort(key=lambda d: d.pnl_pct)
    return closable


def realised_pnl_estimate(position: PositionSnapshot) -> float:
    """Dollar P&L if the position were closed at the current mark."""
    return (
        (position.current_price - position.avg_entry_price)
        * position.qty
        * OPTION_MULTIPLIER
    )
