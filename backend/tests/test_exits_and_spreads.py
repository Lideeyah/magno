"""Exit rules and defined-risk spread construction.

Two P0 gaps found in audit:

* The agent had no exit logic at all. It opened positions, hedged them, and let
  them decay into expiry. For a book judged on P&L that is a slow loss by
  construction.
* A sell signal submitted a naked single leg. The mandate promises defined
  risk; a naked short call has unbounded loss.

The long/short asymmetry is the thing most likely to be got wrong, so it is
tested from both sides throughout.
"""

from __future__ import annotations

import pytest

from app.quant.exit_rules import (
    ExitPolicy,
    evaluate_exit,
    evaluate_exits,
    position_pnl_pct,
    realised_pnl_estimate,
)
from app.quant.hedge_engine import PositionSnapshot
from app.quant.spreads import build_vertical, select_wing, validate_vertical

from .test_tools import make_contract


def option(qty: float, entry: float, current: float, dte: float = 40.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY261218C00450000",
        underlying="SPY",
        asset_class="us_option",
        qty=qty,
        market_value=current * qty * 100,
        unrealized_pl=(current - entry) * qty * 100,
        avg_entry_price=entry,
        current_price=current,
        dte=dte,
    )


def equity(qty: float) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="SPY",
        underlying="SPY",
        asset_class="us_equity",
        qty=qty,
        market_value=qty * 450,
        unrealized_pl=0.0,
        avg_entry_price=450.0,
        current_price=450.0,
    )


# --------------------------------------------------------------------------- #
# P&L sign convention
# --------------------------------------------------------------------------- #
def test_long_profits_when_premium_rises():
    assert position_pnl_pct(option(1, 2.00, 3.00)) == pytest.approx(0.50)


def test_short_profits_when_premium_falls():
    """The sign flips with qty, so one take-profit threshold serves both."""
    assert position_pnl_pct(option(-1, 2.00, 1.00)) == pytest.approx(0.50)


def test_long_loses_when_premium_falls():
    assert position_pnl_pct(option(1, 2.00, 1.00)) == pytest.approx(-0.50)


def test_short_loses_when_premium_rises():
    assert position_pnl_pct(option(-1, 2.00, 4.00)) == pytest.approx(-1.00)


def test_zero_entry_price_is_unpriceable():
    assert position_pnl_pct(option(1, 0.0, 1.0)) is None


# --------------------------------------------------------------------------- #
# Take profit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("qty,entry,current", [(1, 2.00, 3.00), (-1, 2.00, 1.00)])
def test_take_profit_fires_at_fifty_percent_for_both_sides(qty, entry, current):
    decision = evaluate_exit(option(qty, entry, current))
    assert decision.should_close
    assert "TAKE_PROFIT" in {t.code for t in decision.triggers}


def test_take_profit_does_not_fire_below_target():
    assert not evaluate_exit(option(1, 2.00, 2.80)).should_close


def test_take_profit_threshold_is_configurable():
    policy = ExitPolicy(take_profit_pct=0.25)
    assert evaluate_exit(option(1, 2.00, 2.60), policy).should_close


# --------------------------------------------------------------------------- #
# Stop loss — the asymmetry
# --------------------------------------------------------------------------- #
def test_short_stops_when_the_option_doubles():
    """Loss equals the credit received."""
    decision = evaluate_exit(option(-1, 2.00, 4.00))
    assert decision.should_close
    assert "STOP_LOSS" in {t.code for t in decision.triggers}


def test_short_does_not_stop_before_the_credit_is_lost():
    assert not evaluate_exit(option(-1, 2.00, 3.50)).should_close


def test_long_stops_at_half_the_debit_not_at_minus_one_hundred():
    """A long can only lose 100% — it expires worthless. A -100% stop is a
    description of doing nothing, so longs cut earlier."""
    decision = evaluate_exit(option(1, 2.00, 1.00))
    assert decision.should_close
    assert "STOP_LOSS" in {t.code for t in decision.triggers}


def test_long_and_short_stops_are_genuinely_different():
    """Down 50%: the long is stopped out, the short is not."""
    assert evaluate_exit(option(1, 2.00, 1.00)).should_close
    assert not evaluate_exit(option(-1, 2.00, 3.00)).should_close


# --------------------------------------------------------------------------- #
# Time stop
# --------------------------------------------------------------------------- #
def test_time_stop_fires_inside_twenty_one_days():
    decision = evaluate_exit(option(-1, 2.00, 1.90, dte=20.0))
    assert decision.should_close
    assert "TIME_STOP" in {t.code for t in decision.triggers}


def test_time_stop_fires_exactly_on_the_boundary():
    assert evaluate_exit(option(-1, 2.00, 1.90, dte=21.0)).should_close


def test_time_stop_does_not_fire_outside_the_window():
    assert not evaluate_exit(option(-1, 2.00, 1.90, dte=22.0)).should_close


def test_time_stop_fires_on_a_profitable_position_too():
    """Gamma risk near expiry is a reason to leave regardless of P&L."""
    decision = evaluate_exit(option(-1, 2.00, 1.95, dte=10.0))
    assert decision.should_close


def test_a_position_can_trip_several_rules_at_once():
    decision = evaluate_exit(option(-1, 2.00, 0.50, dte=5.0))
    codes = {t.code for t in decision.triggers}
    assert {"TAKE_PROFIT", "TIME_STOP"} <= codes


# --------------------------------------------------------------------------- #
# Scope
# --------------------------------------------------------------------------- #
def test_equity_hedge_legs_are_never_closed_by_exit_rules():
    """They are hedges. Closing one would knock the book directional."""
    assert not evaluate_exit(equity(-55.0)).should_close


def test_closed_positions_are_ignored():
    assert not evaluate_exit(option(0, 2.00, 4.00)).should_close


def test_exits_are_ordered_worst_first():
    """When buying power is tight the loser is the one that keeps growing."""
    positions = [option(1, 2.00, 3.00), option(-1, 2.00, 5.00)]
    positions[1].symbol = "SPY261218P00450000"
    decisions = evaluate_exits(positions)
    assert decisions[0].pnl_pct < decisions[-1].pnl_pct


def test_evaluate_exits_returns_only_closable_positions():
    positions = [option(1, 2.00, 2.05), option(1, 2.00, 3.00)]
    positions[1].symbol = "SPY261218P00450000"
    assert len(evaluate_exits(positions)) == 1


def test_realised_pnl_uses_the_contract_multiplier():
    assert realised_pnl_estimate(option(2, 2.00, 3.00)) == pytest.approx(200.0)
    assert realised_pnl_estimate(option(-2, 2.00, 3.00)) == pytest.approx(-200.0)


# --------------------------------------------------------------------------- #
# Wing selection
# --------------------------------------------------------------------------- #
def call_chain(strikes, bid=2.00, ask=2.10):
    return [
        make_contract(strike=s, dte=30, right="C", bid=max(0.05, bid - i * 0.4),
                      ask=max(0.10, ask - i * 0.4))
        for i, s in enumerate(strikes)
    ]


def test_call_wing_is_above_the_short_strike():
    chain = call_chain([450, 455, 460])
    wing = select_wing(chain[0], chain)
    assert wing is not None and wing.strike > chain[0].strike


def test_put_wing_is_below_the_short_strike():
    chain = [make_contract(strike=s, dte=30, right="P") for s in (440, 445, 450)]
    short = chain[-1]
    wing = select_wing(short, chain)
    assert wing is not None and wing.strike < short.strike


def test_narrowest_qualifying_wing_wins():
    """It caps the loss most tightly and costs the least buying power."""
    chain = call_chain([450, 455, 460, 470])
    assert select_wing(chain[0], chain).strike == 455


def test_wings_outside_the_width_band_are_ignored():
    chain = call_chain([450, 500])
    assert select_wing(chain[0], chain, max_width=25.0) is None


def test_wing_must_share_the_expiry():
    short = make_contract(strike=450, dte=30, right="C")
    far = make_contract(strike=455, dte=45, right="C")
    assert select_wing(short, [short, far]) is None


def test_wing_must_share_the_right():
    short = make_contract(strike=450, dte=30, right="C")
    put = make_contract(strike=455, dte=30, right="P")
    assert select_wing(short, [short, put]) is None


def test_unquotable_wing_is_rejected():
    """An unfillable wing leaves the short leg naked — the exact risk avoided."""
    short = make_contract(strike=450, dte=30, right="C")
    dead = make_contract(strike=455, dte=30, right="C", bid=0.0, ask=0.0)
    assert select_wing(short, [short, dead]) is None


# --------------------------------------------------------------------------- #
# Spread economics
# --------------------------------------------------------------------------- #
def test_max_loss_is_width_minus_credit():
    chain = call_chain([450, 455])
    spread = build_vertical(chain[0], chain, contracts=1)
    assert spread is not None
    assert spread.width == pytest.approx(5.0)
    assert spread.max_loss == pytest.approx(5.0 - spread.net_credit)


def test_loss_is_bounded_which_is_the_entire_point():
    chain = call_chain([450, 455])
    spread = build_vertical(chain[0], chain, contracts=1)
    assert spread.max_loss is not None and spread.max_loss < spread.width


def test_capital_at_risk_scales_with_contracts():
    chain = call_chain([450, 455])
    one = build_vertical(chain[0], chain, contracts=1)
    three = build_vertical(chain[0], chain, contracts=3)
    assert three.capital_at_risk == pytest.approx(one.capital_at_risk * 3)


def test_a_debit_structure_is_rejected():
    """If the wing costs more than the short leg pays, it is not a credit
    spread and should never be opened."""
    short = make_contract(strike=450, dte=30, right="C", bid=1.00, ask=1.10)
    wing = make_contract(strike=455, dte=30, right="C", bid=3.00, ask=3.10)
    spread = build_vertical(short, [short, wing], contracts=1)
    ok, reason = validate_vertical(spread)
    assert not ok and "debit" in reason.lower()


def test_a_trivial_credit_relative_to_risk_is_rejected():
    """Four spread crossings have to be paid for."""
    short = make_contract(strike=450, dte=30, right="C", bid=1.00, ask=1.05)
    wing = make_contract(strike=470, dte=30, right="C", bid=0.95, ask=1.00)
    spread = build_vertical(short, [short, wing], contracts=1, max_width=25.0)
    ok, reason = validate_vertical(spread)
    assert not ok and "credit/risk" in reason.lower()


def test_a_healthy_credit_spread_validates():
    short = make_contract(strike=450, dte=30, right="C", bid=3.00, ask=3.10)
    wing = make_contract(strike=455, dte=30, right="C", bid=1.00, ask=1.10)
    spread = build_vertical(short, [short, wing], contracts=1)
    ok, _ = validate_vertical(spread)
    assert ok


def test_net_delta_of_a_call_credit_spread_is_negative():
    """Short the nearer strike, long the further one: net short delta."""
    chain = call_chain([450, 460])
    spread = build_vertical(chain[0], chain, contracts=1)
    assert spread.net_delta is not None and spread.net_delta < 0


def test_build_returns_none_when_no_wing_exists():
    short = make_contract(strike=450, dte=30, right="C")
    assert build_vertical(short, [short], contracts=1) is None
