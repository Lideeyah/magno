"""Vertical spread construction.

The mandate promises *defined-risk* positions. Until now a sell signal submitted
a single short leg, which is the opposite of defined risk: a naked short call
has unbounded loss. Delta hedging bounds it in practice, but a gap through the
strike between two five-second hedge ticks is unbounded in theory, and "in
theory" is where account-ending losses live.

A vertical spread fixes that by construction. Sell the strike the signal chose,
buy a wing further out of the money in the same expiry. The long wing caps the
loss at the width of the spread minus the credit received, and it does so
mechanically — no hedging, no monitoring, nothing that can fail at 4am.

Long premium does not need this treatment: a debit position already has bounded
loss (the debit). So spreads are constructed only for the short side, and a
single long leg passes through unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

# Wing selection walks outward from the short strike. A wing that is too close
# leaves almost no credit; too far and the position approaches naked risk again
# while consuming buying power.
DEFAULT_MIN_WIDTH = 1.0
DEFAULT_MAX_WIDTH = 25.0


@dataclass(frozen=True)
class SpreadLeg:
    symbol: str
    side: str  # "buy" | "sell"
    strike: float
    bid: float | None
    ask: float | None
    mid: float | None
    delta: float | None


@dataclass
class VerticalSpread:
    """A two-leg defined-risk structure, priced as a single package."""

    underlying: str
    right: str
    expiry: str
    short_leg: SpreadLeg
    long_leg: SpreadLeg
    contracts: int

    @property
    def width(self) -> float:
        """Distance between strikes, in dollars per share."""
        return abs(self.long_leg.strike - self.short_leg.strike)

    @property
    def net_credit(self) -> float | None:
        """Credit per share received to open, at mid.

        Positive means money in. A vertical built from a sell signal should
        always be a credit; a debit means the wing costs more than the short
        leg pays, and the structure is not worth opening.
        """
        if self.short_leg.mid is None or self.long_leg.mid is None:
            return None
        return self.short_leg.mid - self.long_leg.mid

    @property
    def max_loss(self) -> float | None:
        """Worst case per share. This is the whole point of the structure."""
        credit = self.net_credit
        if credit is None:
            return None
        return max(self.width - credit, 0.0)

    @property
    def max_profit(self) -> float | None:
        return self.net_credit

    @property
    def net_delta(self) -> float | None:
        """Delta per contract-pair, per share."""
        if self.short_leg.delta is None or self.long_leg.delta is None:
            return None
        return self.long_leg.delta - self.short_leg.delta

    @property
    def capital_at_risk(self) -> float | None:
        """Dollars the broker will hold against this position."""
        loss = self.max_loss
        return None if loss is None else loss * 100.0 * self.contracts

    @property
    def credit_to_risk(self) -> float | None:
        """Reward-to-risk. Below roughly 0.20 the structure rarely pays for its
        own transaction costs."""
        credit, loss = self.net_credit, self.max_loss
        if credit is None or loss is None or loss <= 0:
            return None
        return credit / loss

    def as_dict(self) -> dict:
        return {
            "underlying": self.underlying,
            "right": self.right,
            "expiry": self.expiry,
            "contracts": self.contracts,
            "short_symbol": self.short_leg.symbol,
            "long_symbol": self.long_leg.symbol,
            "short_strike": self.short_leg.strike,
            "long_strike": self.long_leg.strike,
            "width": self.width,
            "net_credit": self.net_credit,
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "net_delta": self.net_delta,
            "capital_at_risk": self.capital_at_risk,
            "credit_to_risk": self.credit_to_risk,
        }


def _to_leg(contract, side: str) -> SpreadLeg:
    return SpreadLeg(
        symbol=contract.symbol,
        side=side,
        strike=contract.strike,
        bid=contract.bid,
        ask=contract.ask,
        mid=contract.mid,
        delta=contract.greeks.delta if contract.greeks else None,
    )


def select_wing(
    short_contract,
    chain: list,
    *,
    min_width: float = DEFAULT_MIN_WIDTH,
    max_width: float = DEFAULT_MAX_WIDTH,
):
    """Pick the long wing for a short leg.

    Constraints, in order of importance:

    * Same underlying, expiry and right — otherwise it is not a vertical.
    * Further out of the money than the short strike. For a call that means a
      *higher* strike; for a put, a *lower* one. Getting this backwards builds
      a debit spread pointing the wrong way.
    * Actually quotable. A wing with no bid cannot be bought reliably, and an
      unfillable wing leaves the short leg naked — the exact risk being avoided.

    Among the candidates, the narrowest qualifying width wins: it caps the loss
    most tightly and consumes the least buying power.
    """
    is_call = short_contract.right == "C"

    candidates = []
    for c in chain:
        if c.symbol == short_contract.symbol:
            continue
        if c.underlying != short_contract.underlying:
            continue
        if c.right != short_contract.right or c.expiry != short_contract.expiry:
            continue
        # Further OTM than the short strike.
        if is_call and c.strike <= short_contract.strike:
            continue
        if not is_call and c.strike >= short_contract.strike:
            continue

        width = abs(c.strike - short_contract.strike)
        if width < min_width or width > max_width:
            continue
        # The wing is bought, so it needs a real offer to lift.
        if not c.ask or c.ask <= 0 or not c.tradable:
            continue
        candidates.append((width, c))

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def build_vertical(
    short_contract,
    chain: list,
    contracts: int = 1,
    *,
    min_width: float = DEFAULT_MIN_WIDTH,
    max_width: float = DEFAULT_MAX_WIDTH,
) -> VerticalSpread | None:
    """Assemble a credit vertical around a chosen short strike."""
    wing = select_wing(
        short_contract, chain, min_width=min_width, max_width=max_width
    )
    if wing is None:
        return None

    return VerticalSpread(
        underlying=short_contract.underlying,
        right=short_contract.right,
        expiry=short_contract.expiry,
        short_leg=_to_leg(short_contract, "sell"),
        long_leg=_to_leg(wing, "buy"),
        contracts=contracts,
    )


def validate_vertical(spread: VerticalSpread, min_credit_to_risk: float = 0.15) -> tuple[bool, str]:
    """Reject structures that are not worth opening.

    A vertical that pays a trivial credit relative to its maximum loss is a
    bad trade even when every liquidity gate passes: the reward does not cover
    the two spreads crossed to get in and the two to get out.
    """
    credit = spread.net_credit
    if credit is None:
        return False, "One or both legs are unquotable; the spread cannot be priced."
    if credit <= 0:
        return False, (
            f"Structure is a ${abs(credit):.2f} debit, not a credit — the wing costs "
            "more than the short leg pays."
        )
    if spread.width <= 0:
        return False, "Both legs share a strike; this is not a vertical."

    ratio = spread.credit_to_risk
    if ratio is not None and ratio < min_credit_to_risk:
        return False, (
            f"Credit/risk {ratio:.2f} below the {min_credit_to_risk:.2f} floor — "
            f"${credit:.2f} credit against ${spread.max_loss:.2f} of risk does not "
            "cover four spread crossings."
        )
    return True, (
        f"${credit:.2f} credit on ${spread.width:.2f} width — max loss "
        f"${spread.max_loss:.2f}/share, credit/risk {ratio:.2f}"
        if ratio is not None
        else f"${credit:.2f} credit on ${spread.width:.2f} width"
    )
