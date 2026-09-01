"""Deterministic pre-trade risk gates.

Every order Magno submits -- whether proposed by the LLM reasoner or by the
autonomous hedge loop -- passes through :func:`evaluate_option_order` or
:func:`evaluate_hedge_order` first. The gates are pure functions over plain
data: no network, no clock reads beyond what is passed in, no LLM. That is the
point. The model may *propose*; only arithmetic may *approve*.

Each check returns a :class:`Check` record which is streamed verbatim to the
execution audit log, so a judge can replay exactly why any given contract was
admitted or rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# Threshold comparisons are done with this tolerance so a value sitting exactly
# on a limit is admitted rather than rejected by float64 representation error.
FLOAT_TOL = 1e-9


class Verdict(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    WARN = "WARN"


@dataclass(frozen=True)
class Check:
    code: str
    verdict: Verdict
    message: str
    observed: float | None = None
    limit: float | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not Verdict.REJECT

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "verdict": self.verdict.value,
            "message": self.message,
            "observed": self.observed,
            "limit": self.limit,
        }


@dataclass
class GateResult:
    checks: list[Check] = field(default_factory=list)

    def add(self, check: Check) -> "GateResult":
        self.checks.append(check)
        return self

    @property
    def approved(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def rejections(self) -> list[Check]:
        return [c for c in self.checks if c.verdict is Verdict.REJECT]

    @property
    def summary(self) -> str:
        if self.approved:
            warns = [c for c in self.checks if c.verdict is Verdict.WARN]
            base = f"{len(self.checks)} gates cleared"
            return f"{base} ({len(warns)} warning)" if warns else base
        return "; ".join(f"{c.code}: {c.message}" for c in self.rejections)

    def as_dict(self) -> dict:
        return {
            "approved": self.approved,
            "summary": self.summary,
            "checks": [c.as_dict() for c in self.checks],
        }


@dataclass(frozen=True)
class RiskEnvelope:
    """Per-session risk configuration, set during onboarding."""

    max_spread_pct: float = 0.05
    max_allocation_pct: float = 0.10
    delta_drift_threshold: float = 1.0
    max_daily_loss_pct: float = 0.05
    max_open_positions: int = 6
    # The entry floor must sit clear of the exit engine's time stop, or the
    # two rules fight: a position opened inside the time-stop window is closed
    # on the very next tick, round-tripping the spread for nothing. Observed
    # live -- a 17.2 DTE put was bought at 4.85 and stopped out at 4.75 one
    # second later, and would have repeated once a minute.
    #
    # 28 gives a position a full week of life before the 21-day stop can reach
    # it. `validate_dte_against_exit` enforces the relationship.
    min_dte: float = 28.0
    max_dte: float = 60.0
    min_open_interest: int = 100
    min_option_price: float = 0.10
    max_option_price: float = 40.0

    # Volatility policy. These are the operator's dials, not the agent's: the
    # IV-rank percentile at which premium is considered rich enough to sell, or
    # cheap enough to buy. Defaults come from the selected strategy at
    # onboarding and can be overridden per session. Either may be None, which
    # disables that side entirely.
    iv_rank_sell_at: float | None = 65.0
    iv_rank_buy_at: float | None = 35.0

    def signal_for(self, iv_rank: float | None) -> str | None:
        """'sell', 'buy', or None when the rank sits in the neutral band.

        Single source of truth for the decision boundary. The reasoner's prompt,
        the deterministic fallback and the divergence check all read this, so
        the model can never be shown a rule that the fallback disagrees with.
        """
        if iv_rank is None:
            return None
        if self.iv_rank_sell_at is not None and iv_rank >= self.iv_rank_sell_at:
            return "sell"
        if self.iv_rank_buy_at is not None and iv_rank <= self.iv_rank_buy_at:
            return "buy"
        return None

    @property
    def decision_rule(self) -> str:
        """The volatility policy stated as arithmetic, for the system prompt."""
        clauses = []
        if self.iv_rank_sell_at is not None:
            clauses.append(
                f"IV rank >= {self.iv_rank_sell_at:.0f}  ->  premium is rich, selling is the edge"
            )
        if self.iv_rank_buy_at is not None:
            clauses.append(
                f"IV rank <= {self.iv_rank_buy_at:.0f}  ->  premium is cheap, buying is the edge"
            )
        clauses.append("otherwise  ->  no measurable edge")
        return "\n".join(f"  {c}" for c in clauses)

    def as_dict(self) -> dict:
        return {
            "max_spread_pct": self.max_spread_pct,
            "max_allocation_pct": self.max_allocation_pct,
            "delta_drift_threshold": self.delta_drift_threshold,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_open_positions": self.max_open_positions,
            "min_dte": self.min_dte,
            "max_dte": self.max_dte,
            "min_open_interest": self.min_open_interest,
            "min_option_price": self.min_option_price,
            "max_option_price": self.max_option_price,
            "iv_rank_sell_at": self.iv_rank_sell_at,
            "iv_rank_buy_at": self.iv_rank_buy_at,
        }


# --------------------------------------------------------------------------- #
# Primitive gates
# --------------------------------------------------------------------------- #
def mid_price(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


def spread_pct(bid: float | None, ask: float | None) -> float | None:
    mid = mid_price(bid, ask)
    if mid is None or mid <= 0:
        return None
    return (ask - bid) / mid


def validate_spread(bid: float | None, ask: float | None, max_pct: float = 0.05) -> Check:
    """The headline liquidity gate: reject when (ask-bid)/mid exceeds ``max_pct``.

    A missing or crossed quote is a rejection, not a pass -- an option we cannot
    price is an option we cannot risk-manage.
    """
    if bid is None or ask is None:
        return Check("SPREAD_NO_QUOTE", Verdict.REJECT, "No two-sided NBBO quote available")
    if bid <= 0 or ask <= 0:
        return Check(
            "SPREAD_ZERO_BID",
            Verdict.REJECT,
            f"Non-positive quote (bid={bid:.2f}, ask={ask:.2f})",
            observed=bid,
        )
    if ask < bid:
        return Check(
            "SPREAD_CROSSED",
            Verdict.REJECT,
            f"Crossed market (bid={bid:.2f} > ask={ask:.2f})",
            observed=ask - bid,
        )
    pct = spread_pct(bid, ask)
    if pct is None:
        return Check("SPREAD_NO_MID", Verdict.REJECT, "Mid price could not be derived")
    # Compare with a tolerance: a quote sitting exactly on the cap lands at
    # 0.05000000000000004 in float64 and must not be rejected for it.
    if pct > max_pct + FLOAT_TOL:
        return Check(
            "SPREAD_TOO_WIDE",
            Verdict.REJECT,
            f"Spread {pct:.2%} exceeds {max_pct:.2%} cap",
            observed=pct,
            limit=max_pct,
        )
    verdict = Verdict.WARN if pct > max_pct * 0.75 else Verdict.PASS
    return Check(
        "SPREAD_OK",
        verdict,
        f"Spread {pct:.2%} within {max_pct:.2%} cap",
        observed=pct,
        limit=max_pct,
    )


def validate_allocation(notional: float, buying_power: float, max_pct: float = 0.10) -> Check:
    """Cap a single trade at ``max_pct`` of buying power."""
    if buying_power <= 0:
        return Check("ALLOC_NO_BP", Verdict.REJECT, "No buying power available", observed=buying_power)
    pct = notional / buying_power
    if pct > max_pct + FLOAT_TOL:
        return Check(
            "ALLOC_EXCEEDS_CAP",
            Verdict.REJECT,
            f"Notional ${notional:,.0f} is {pct:.2%} of buying power (cap {max_pct:.0%})",
            observed=pct,
            limit=max_pct,
        )
    return Check(
        "ALLOC_OK",
        Verdict.PASS,
        f"Notional ${notional:,.0f} = {pct:.2%} of buying power",
        observed=pct,
        limit=max_pct,
    )


def validate_dte(dte: float, min_dte: float, max_dte: float) -> Check:
    if dte < min_dte:
        return Check(
            "DTE_TOO_NEAR",
            Verdict.REJECT,
            f"{dte:.1f} DTE below {min_dte:.0f}d floor (gamma/pin risk)",
            observed=dte,
            limit=min_dte,
        )
    if dte > max_dte:
        return Check(
            "DTE_TOO_FAR",
            Verdict.REJECT,
            f"{dte:.1f} DTE above {max_dte:.0f}d ceiling (capital efficiency)",
            observed=dte,
            limit=max_dte,
        )
    return Check("DTE_OK", Verdict.PASS, f"{dte:.1f} DTE within [{min_dte:.0f}, {max_dte:.0f}]", observed=dte)


def validate_open_interest(open_interest: int | None, minimum: int) -> Check:
    if open_interest is None:
        return Check("OI_UNKNOWN", Verdict.WARN, "Open interest unavailable from feed", limit=float(minimum))
    if open_interest < minimum:
        return Check(
            "OI_TOO_THIN",
            Verdict.REJECT,
            f"Open interest {open_interest:,} below {minimum:,} floor",
            observed=float(open_interest),
            limit=float(minimum),
        )
    return Check(
        "OI_OK", Verdict.PASS, f"Open interest {open_interest:,}", observed=float(open_interest), limit=float(minimum)
    )


def validate_price_band(price: float, envelope: RiskEnvelope) -> Check:
    if price < envelope.min_option_price:
        return Check(
            "PRICE_TOO_LOW",
            Verdict.REJECT,
            f"Mid ${price:.2f} below ${envelope.min_option_price:.2f} floor (lottery ticket)",
            observed=price,
            limit=envelope.min_option_price,
        )
    if price > envelope.max_option_price:
        return Check(
            "PRICE_TOO_HIGH",
            Verdict.REJECT,
            f"Mid ${price:.2f} above ${envelope.max_option_price:.2f} ceiling",
            observed=price,
            limit=envelope.max_option_price,
        )
    return Check("PRICE_OK", Verdict.PASS, f"Mid ${price:.2f} in band", observed=price)


def validate_iv(iv: float | None) -> Check:
    if iv is None:
        return Check("IV_UNSOLVABLE", Verdict.REJECT, "Implied vol did not invert; quote violates arbitrage bounds")
    if iv <= 0.01 or iv >= 3.0:
        return Check(
            "IV_IMPLAUSIBLE",
            Verdict.REJECT,
            f"Implied vol {iv:.1%} outside plausible 1%-300% band",
            observed=iv,
        )
    return Check("IV_OK", Verdict.PASS, f"Implied vol {iv:.1%}", observed=iv)


def validate_position_count(open_positions: int, maximum: int) -> Check:
    if open_positions >= maximum:
        return Check(
            "CONCENTRATION_CAP",
            Verdict.REJECT,
            f"{open_positions} open positions at cap of {maximum}",
            observed=float(open_positions),
            limit=float(maximum),
        )
    return Check(
        "CONCENTRATION_OK",
        Verdict.PASS,
        f"{open_positions}/{maximum} position slots used",
        observed=float(open_positions),
        limit=float(maximum),
    )


def validate_daily_loss(day_pnl: float, equity_at_open: float, max_loss_pct: float) -> Check:
    """Circuit breaker. Once tripped the autopilot stops opening new risk."""
    if equity_at_open <= 0:
        return Check("HALT_NO_BASE", Verdict.WARN, "Opening equity unknown; loss breaker inactive")
    loss_pct = -day_pnl / equity_at_open
    if loss_pct >= max_loss_pct:
        return Check(
            "DAILY_LOSS_HALT",
            Verdict.REJECT,
            f"Day P&L {day_pnl:,.0f} is {loss_pct:.2%} drawdown, breaker at {max_loss_pct:.0%}",
            observed=loss_pct,
            limit=max_loss_pct,
        )
    return Check(
        "DAILY_LOSS_OK",
        Verdict.PASS,
        f"Day drawdown {max(loss_pct, 0.0):.2%} under {max_loss_pct:.0%} breaker",
        observed=max(loss_pct, 0.0),
        limit=max_loss_pct,
    )


def validate_dte_against_exit(min_dte: float, time_stop_dte: float) -> Check:
    """The entry window and the exit time stop must not overlap.

    Two rules that are each individually sensible can be jointly incoherent.
    Entering at 5 DTE is defensible; closing at 21 DTE is defensible; doing
    both means every trade inside that band is opened and immediately closed,
    paying the spread twice for no exposure. This makes the relationship a
    checked invariant rather than a coincidence of defaults.
    """
    if min_dte <= time_stop_dte:
        return Check(
            "DTE_WINDOW_CONFLICT",
            Verdict.REJECT,
            f"Entry floor {min_dte:.0f} DTE is at or inside the {time_stop_dte:.0f}d "
            f"exit time stop; every position opened would be closed immediately",
            observed=min_dte,
            limit=time_stop_dte,
        )
    return Check(
        "DTE_WINDOW_OK",
        Verdict.PASS,
        f"Entry floor {min_dte:.0f} DTE clears the {time_stop_dte:.0f}d time stop "
        f"by {min_dte - time_stop_dte:.0f} days",
        observed=min_dte,
        limit=time_stop_dte,
    )


def validate_market_open(is_open: bool) -> Check:
    if not is_open:
        return Check("MARKET_CLOSED", Verdict.REJECT, "US equity market is closed; no new risk")
    return Check("MARKET_OPEN", Verdict.PASS, "Market open")


# --------------------------------------------------------------------------- #
# Composite gates
# --------------------------------------------------------------------------- #
def evaluate_option_order(
    *,
    bid: float | None,
    ask: float | None,
    iv: float | None,
    dte: float,
    open_interest: int | None,
    contracts: int,
    buying_power: float,
    open_positions: int,
    day_pnl: float,
    equity_at_open: float,
    market_open: bool,
    envelope: RiskEnvelope,
) -> GateResult:
    """Full pre-trade chain for an options entry. Order matters: cheapest and
    most decisive checks first so the audit log reads as a funnel."""
    result = GateResult()
    result.add(validate_market_open(market_open))
    result.add(validate_daily_loss(day_pnl, equity_at_open, envelope.max_daily_loss_pct))
    result.add(validate_position_count(open_positions, envelope.max_open_positions))
    result.add(validate_spread(bid, ask, envelope.max_spread_pct))

    mid = mid_price(bid, ask)
    if mid is None:
        return result  # spread gate already recorded the rejection

    result.add(validate_price_band(mid, envelope))
    result.add(validate_dte(dte, envelope.min_dte, envelope.max_dte))
    result.add(validate_open_interest(open_interest, envelope.min_open_interest))
    result.add(validate_iv(iv))
    # Option notional: premium per share x 100 shares x contracts.
    result.add(validate_allocation(mid * 100.0 * contracts, buying_power, envelope.max_allocation_pct))
    return result


def evaluate_hedge_order(
    *,
    qty: float,
    price: float,
    buying_power: float,
    market_open: bool,
    envelope: RiskEnvelope,
) -> GateResult:
    """Hedges are corrective, so they bypass the concentration and loss-halt
    gates -- a circuit breaker must never trap the book in a directional
    position. They still respect market hours and the allocation cap."""
    result = GateResult()
    result.add(validate_market_open(market_open))
    notional = abs(qty) * price
    if notional < 1.0:
        result.add(
            Check(
                "HEDGE_BELOW_MIN_NOTIONAL",
                Verdict.REJECT,
                f"Hedge notional ${notional:.2f} below Alpaca's $1.00 fractional minimum",
                observed=notional,
                limit=1.0,
            )
        )
        return result
    result.add(
        Check("HEDGE_NOTIONAL_OK", Verdict.PASS, f"Hedge notional ${notional:,.2f}", observed=notional, limit=1.0)
    )
    result.add(validate_allocation(notional, buying_power, max(envelope.max_allocation_pct, 0.25)))
    return result
