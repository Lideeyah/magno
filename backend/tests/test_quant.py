"""Correctness tests for the pricing, gating and hedging core.

These are the parts of Magno that decide whether real capital moves, so they are
tested against closed-form identities and finite-difference checks rather than
golden values copied out of the implementation.

    cd backend && .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pytest

from app.quant.greeks import (
    Greeks,
    bs_greeks,
    bs_price,
    implied_volatility,
    parse_occ,
    percentile_rank,
    realized_volatility,
)
from app.quant.hedge_engine import (
    PositionSnapshot,
    aggregate_portfolio,
    apply_price_shock,
    compute_hedge_intents,
)
from app.quant.risk_gate import (
    RiskEnvelope,
    Verdict,
    evaluate_hedge_order,
    evaluate_option_order,
    spread_pct,
    validate_allocation,
    validate_spread,
)

S, K, T, R = 450.0, 455.0, 0.25, 0.0425
SIGMA = 0.22


# --------------------------------------------------------------------------- #
# Black-Scholes
# --------------------------------------------------------------------------- #
def test_put_call_parity():
    """C - P == S*e^(-qT) - K*e^(-rT). The single strongest check on pricing."""
    call = bs_price(S, K, T, R, SIGMA, is_call=True)
    put = bs_price(S, K, T, R, SIGMA, is_call=False)
    assert call - put == pytest.approx(S - K * math.exp(-R * T), abs=1e-9)


def test_price_is_monotonic_in_vol():
    prices = [bs_price(S, K, T, R, sig, True) for sig in (0.05, 0.15, 0.30, 0.60)]
    assert prices == sorted(prices)


def test_deep_itm_call_approaches_intrinsic():
    price = bs_price(S, 100.0, T, R, 0.05, is_call=True)
    assert price == pytest.approx(S - 100.0 * math.exp(-R * T), abs=0.01)


def test_deep_otm_call_is_near_zero():
    assert bs_price(S, 2000.0, T, R, SIGMA, is_call=True) < 1e-6


@pytest.mark.parametrize("is_call", [True, False])
def test_delta_bounds_and_sign(is_call):
    d = bs_greeks(S, K, T, R, SIGMA, is_call).delta
    assert (0.0 < d < 1.0) if is_call else (-1.0 < d < 0.0)


def test_call_put_delta_parity():
    """δ_call - δ_put == e^(-qT) == 1 at zero dividend yield."""
    dc = bs_greeks(S, K, T, R, SIGMA, True).delta
    dp = bs_greeks(S, K, T, R, SIGMA, False).delta
    assert dc - dp == pytest.approx(1.0, abs=1e-9)


def test_atm_delta_is_near_half():
    d = bs_greeks(S, S, T, R, SIGMA, True).delta
    assert 0.50 < d < 0.60  # slightly above 0.5 from the drift term


@pytest.mark.parametrize("is_call", [True, False])
def test_delta_matches_finite_difference(is_call):
    """δ = ∂V/∂S, verified by central difference on the pricer."""
    h = 0.01
    up = bs_price(S + h, K, T, R, SIGMA, is_call)
    dn = bs_price(S - h, K, T, R, SIGMA, is_call)
    assert bs_greeks(S, K, T, R, SIGMA, is_call).delta == pytest.approx((up - dn) / (2 * h), abs=1e-5)


@pytest.mark.parametrize("is_call", [True, False])
def test_gamma_matches_finite_difference(is_call):
    """Γ = ∂²V/∂S², and Γ_call == Γ_put."""
    h = 0.05
    up = bs_price(S + h, K, T, R, SIGMA, is_call)
    mid = bs_price(S, K, T, R, SIGMA, is_call)
    dn = bs_price(S - h, K, T, R, SIGMA, is_call)
    numeric = (up - 2 * mid + dn) / (h * h)
    assert bs_greeks(S, K, T, R, SIGMA, is_call).gamma == pytest.approx(numeric, rel=1e-3)


def test_gamma_and_vega_are_right_identical():
    c, p = bs_greeks(S, K, T, R, SIGMA, True), bs_greeks(S, K, T, R, SIGMA, False)
    assert c.gamma == pytest.approx(p.gamma, abs=1e-12)
    assert c.vega == pytest.approx(p.vega, abs=1e-12)


def test_vega_matches_finite_difference():
    """Vega is quoted per 1 vol point, so scale the bump by 100."""
    h = 1e-4
    up = bs_price(S, K, T, R, SIGMA + h, True)
    dn = bs_price(S, K, T, R, SIGMA - h, True)
    assert bs_greeks(S, K, T, R, SIGMA, True).vega == pytest.approx((up - dn) / (2 * h) / 100.0, rel=1e-4)


def test_theta_is_negative_for_long_premium_and_per_day():
    """Theta is reported per calendar day, so one day of decay should match."""
    g = bs_greeks(S, K, T, R, SIGMA, True)
    assert g.theta < 0
    one_day = bs_price(S, K, T - 1 / 365.0, R, SIGMA, True) - bs_price(S, K, T, R, SIGMA, True)
    assert g.theta == pytest.approx(one_day, rel=0.02)


def test_greeks_survive_expiry_edge():
    """A contract at the expiry boundary must still yield a usable delta."""
    g = bs_greeks(S, K, 0.0, R, SIGMA, True)
    assert 0.0 <= g.delta <= 1.0 and not math.isnan(g.delta)


# --------------------------------------------------------------------------- #
# Implied volatility
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("strike", [380.0, 440.0, 450.0, 460.0, 520.0])
@pytest.mark.parametrize("sigma", [0.08, 0.22, 0.75, 1.5])
@pytest.mark.parametrize("is_call", [True, False])
def test_iv_round_trips(strike, sigma, is_call):
    """Price at a known sigma, invert, and recover it across the surface."""
    price = bs_price(S, strike, T, R, sigma, is_call)
    if price < 0.01:
        pytest.skip("premium too small to invert meaningfully")
    recovered = implied_volatility(price, S, strike, T, R, is_call)
    assert recovered is not None
    assert recovered == pytest.approx(sigma, rel=1e-3)


def test_iv_rejects_quote_below_intrinsic():
    """A sub-intrinsic quote is an arbitrage violation, not a low-vol option."""
    intrinsic = S - 300.0 * math.exp(-R * T)
    assert implied_volatility(intrinsic - 5.0, S, 300.0, T, R, is_call=True) is None


def test_iv_rejects_quote_above_payoff_cap():
    assert implied_volatility(S + 10.0, S, K, T, R, is_call=True) is None


def test_iv_rejects_non_positive_price():
    assert implied_volatility(0.0, S, K, T, R, is_call=True) is None


# --------------------------------------------------------------------------- #
# OCC symbology
# --------------------------------------------------------------------------- #
def test_parse_occ_call():
    occ = parse_occ("SPY250919C00450000")
    assert occ is not None
    assert (occ.underlying, occ.expiry, occ.is_call, occ.strike) == ("SPY", date(2025, 9, 19), True, 450.0)


def test_parse_occ_put_with_fractional_strike():
    occ = parse_occ("NVDA260116P00137500")
    assert occ is not None
    assert occ.underlying == "NVDA" and occ.strike == 137.5 and not occ.is_call


@pytest.mark.parametrize("bad", ["SPY", "", "SPY250919X00450000", "SPY251399C00450000", "spy250919c00450"])
def test_parse_occ_rejects_malformed(bad):
    assert parse_occ(bad) is None


def test_year_fraction_shrinks_toward_expiry():
    occ = parse_occ("SPY250919C00450000")
    far = occ.year_fraction(datetime(2025, 6, 19, 14, 0, tzinfo=timezone.utc))
    near = occ.year_fraction(datetime(2025, 9, 18, 14, 0, tzinfo=timezone.utc))
    assert far > near > 0


def test_year_fraction_is_floored_past_expiry():
    occ = parse_occ("SPY250919C00450000")
    assert occ.year_fraction(datetime(2026, 1, 1, tzinfo=timezone.utc)) > 0


# --------------------------------------------------------------------------- #
# Realised vol
# --------------------------------------------------------------------------- #
def test_realized_vol_of_flat_series_is_zero():
    assert realized_volatility([100.0] * 30, window=20) == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_scales_with_dispersion():
    calm = [100.0 * (1.001 ** i) if i % 2 else 100.0 * (0.999 ** i) for i in range(40)]
    wild = [100.0 * (1.03 ** i) if i % 2 else 100.0 * (0.97 ** i) for i in range(40)]
    assert realized_volatility(wild, 20) > realized_volatility(calm, 20)


def test_realized_vol_needs_enough_history():
    assert realized_volatility([100.0, 101.0], window=20) is None


def test_percentile_rank_endpoints():
    series = [float(i) for i in range(1, 101)]
    assert percentile_rank(1.0, series) == pytest.approx(1.0)
    assert percentile_rank(100.0, series) == pytest.approx(100.0)
    assert percentile_rank(50.0, series) == pytest.approx(50.0)
    assert percentile_rank(0.0, []) is None


# --------------------------------------------------------------------------- #
# Risk gates
# --------------------------------------------------------------------------- #
def test_spread_pct_uses_mid_as_denominator():
    assert spread_pct(1.00, 1.10) == pytest.approx(0.10 / 1.05)


def test_spread_gate_accepts_tight_and_rejects_wide():
    assert validate_spread(1.00, 1.02, 0.05).verdict is Verdict.PASS
    wide = validate_spread(1.00, 1.20, 0.05)
    assert wide.verdict is Verdict.REJECT and wide.code == "SPREAD_TOO_WIDE"


def test_spread_gate_warns_near_the_cap():
    """0.04/1.02 ≈ 3.9%, inside the 5% cap but past the 75% warning band."""
    assert validate_spread(1.00, 1.04, 0.05).verdict is Verdict.WARN


def test_spread_gate_boundary_is_inclusive():
    """Exactly at the cap must pass -- the rule is 'exceeds 5%'."""
    bid, ask = 1.00, 1.00 * (1 + 0.05 / 2) / (1 - 0.05 / 2)
    assert validate_spread(bid, ask, 0.05).verdict is not Verdict.REJECT


@pytest.mark.parametrize(
    "bid,ask,code",
    [
        (None, 1.0, "SPREAD_NO_QUOTE"),
        (1.0, None, "SPREAD_NO_QUOTE"),
        (0.0, 1.0, "SPREAD_ZERO_BID"),
        (1.20, 1.00, "SPREAD_CROSSED"),
    ],
)
def test_spread_gate_rejects_unusable_quotes(bid, ask, code):
    check = validate_spread(bid, ask, 0.05)
    assert check.verdict is Verdict.REJECT and check.code == code


def test_allocation_cap():
    assert validate_allocation(5_000, 100_000, 0.10).verdict is Verdict.PASS
    assert validate_allocation(15_000, 100_000, 0.10).verdict is Verdict.REJECT
    assert validate_allocation(1_000, 0, 0.10).verdict is Verdict.REJECT


def _order_kwargs(**overrides):
    base = dict(
        bid=2.00,
        ask=2.06,
        iv=0.28,
        dte=30.0,
        open_interest=5_000,
        contracts=1,
        buying_power=100_000.0,
        open_positions=1,
        day_pnl=250.0,
        equity_at_open=100_000.0,
        market_open=True,
        envelope=RiskEnvelope(),
    )
    base.update(overrides)
    return base


def test_clean_option_order_is_approved():
    result = evaluate_option_order(**_order_kwargs())
    assert result.approved and "cleared" in result.summary


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"market_open": False}, "MARKET_CLOSED"),
        ({"day_pnl": -9_000.0}, "DAILY_LOSS_HALT"),
        ({"open_positions": 6}, "CONCENTRATION_CAP"),
        ({"bid": 2.00, "ask": 2.50}, "SPREAD_TOO_WIDE"),
        ({"bid": 0.04, "ask": 0.041}, "PRICE_TOO_LOW"),
        ({"dte": 1.0}, "DTE_TOO_NEAR"),
        ({"dte": 400.0}, "DTE_TOO_FAR"),
        ({"open_interest": 3}, "OI_TOO_THIN"),
        ({"iv": None}, "IV_UNSOLVABLE"),
        ({"contracts": 200}, "ALLOC_EXCEEDS_CAP"),
    ],
)
def test_each_gate_can_veto_independently(overrides, code):
    result = evaluate_option_order(**_order_kwargs(**overrides))
    assert not result.approved
    assert code in {c.code for c in result.rejections}


def test_rejection_summary_names_the_failing_gate():
    result = evaluate_option_order(**_order_kwargs(market_open=False))
    assert "MARKET_CLOSED" in result.summary


def test_hedge_bypasses_the_loss_breaker_but_not_market_hours():
    """A circuit breaker must never trap the book in a directional position."""
    env = RiskEnvelope()
    open_ok = evaluate_hedge_order(qty=3.5, price=450.0, buying_power=100_000, market_open=True, envelope=env)
    closed = evaluate_hedge_order(qty=3.5, price=450.0, buying_power=100_000, market_open=False, envelope=env)
    assert open_ok.approved and not closed.approved


def test_hedge_rejects_below_alpaca_min_notional():
    result = evaluate_hedge_order(qty=0.001, price=450.0, buying_power=100_000, market_open=True, envelope=RiskEnvelope())
    assert not result.approved
    assert "HEDGE_BELOW_MIN_NOTIONAL" in {c.code for c in result.rejections}


# --------------------------------------------------------------------------- #
# Portfolio aggregation & hedging
# --------------------------------------------------------------------------- #
def _option(symbol, underlying, qty, delta, gamma=0.01, theta=-0.05, vega=0.30, price=5.0):
    return PositionSnapshot(
        symbol=symbol,
        underlying=underlying,
        asset_class="us_option",
        qty=qty,
        market_value=qty * price * 100,
        unrealized_pl=0.0,
        avg_entry_price=price,
        current_price=price,
        greeks=Greeks(delta=delta, gamma=gamma, theta=theta, vega=vega, rho=0.0, iv=0.25, price=price),
    )


def _equity(underlying, qty, price):
    return PositionSnapshot(
        symbol=underlying,
        underlying=underlying,
        asset_class="us_equity",
        qty=qty,
        market_value=qty * price,
        unrealized_pl=0.0,
        avg_entry_price=price,
        current_price=price,
    )


def test_option_delta_uses_the_100_multiplier():
    book = aggregate_portfolio([_option("SPY250919C00450000", "SPY", 2, 0.55)], {"SPY": 450.0})
    assert book.net_delta == pytest.approx(0.55 * 2 * 100)


def test_short_options_contribute_negative_delta():
    book = aggregate_portfolio([_option("SPY250919C00450000", "SPY", -3, 0.40)], {"SPY": 450.0})
    assert book.net_delta == pytest.approx(-120.0)


def test_equity_shares_contribute_one_delta_each():
    book = aggregate_portfolio([_equity("SPY", -55.0, 450.0)], {"SPY": 450.0})
    assert book.net_delta == pytest.approx(-55.0)


def test_equity_offsets_option_delta_to_neutral():
    positions = [_option("SPY250919C00450000", "SPY", 1, 0.55), _equity("SPY", -55.0, 450.0)]
    book = aggregate_portfolio(positions, {"SPY": 450.0})
    assert book.net_delta == pytest.approx(0.0, abs=1e-9)
    assert compute_hedge_intents(book, RiskEnvelope(), buying_power=100_000, market_open=True) == []


def test_exposure_is_bucketed_per_underlying():
    positions = [_option("SPY250919C00450000", "SPY", 1, 0.60), _option("QQQ250919P00400000", "QQQ", 2, -0.30)]
    book = aggregate_portfolio(positions, {"SPY": 450.0, "QQQ": 400.0})
    assert book.by_underlying["SPY"].net_delta == pytest.approx(60.0)
    assert book.by_underlying["QQQ"].net_delta == pytest.approx(-60.0)
    assert book.net_delta == pytest.approx(0.0)


def test_offsetting_underlyings_do_not_suppress_per_name_hedges():
    """Portfolio delta nets to zero, but each name is still 60 delta exposed.

    Hedging on the portfolio number alone would leave a live SPY/QQQ basis bet.
    """
    positions = [_option("SPY250919C00450000", "SPY", 1, 0.60), _option("QQQ250919P00400000", "QQQ", 2, -0.30)]
    book = aggregate_portfolio(positions, {"SPY": 450.0, "QQQ": 400.0})
    intents = compute_hedge_intents(book, RiskEnvelope(), buying_power=1_000_000, market_open=True)
    assert {i.underlying: i.side for i in intents} == {"SPY": "sell", "QQQ": "buy"}


def test_hedge_of_a_long_call_uses_whole_shares_because_it_opens_a_short():
    """Neutralising +55.37 delta from flat means selling short, and Alpaca does
    not accept fractional short sales — so the order rounds toward zero."""
    book = aggregate_portfolio([_option("SPY250919C00450000", "SPY", 1, 0.5537)], {"SPY": 450.0})
    intent = compute_hedge_intents(book, RiskEnvelope(), buying_power=1_000_000, market_open=True)[0]
    assert intent.side == "sell"
    assert intent.qty == pytest.approx(55.0)
    assert intent.qty % 1 == 0, "a short hedge must be a whole number of shares"
    # Under-corrects by less than one share, which is inside the drift cap.
    assert 0 <= intent.projected_delta_after < 1.0


def test_hedge_that_only_reduces_a_long_keeps_fractional_precision():
    """Selling out of an existing long is not a short sale, so precision holds.

    A long put (negative delta) against a larger long stock position: the
    correction sells 4.63 shares out of 15 and the account stays long, so there
    is no reason to round.
    """
    positions = [_option("SPY250919P00450000", "SPY", 1, -0.1037), _equity("SPY", 15.0, 450.0)]
    book = aggregate_portfolio(positions, {"SPY": 450.0})
    intent = compute_hedge_intents(book, RiskEnvelope(), buying_power=1_000_000, market_open=True)[0]
    assert intent.side == "sell"
    assert intent.qty % 1 != 0, "no need to round when the position stays long"
    assert abs(intent.projected_delta_after) < 0.001


def test_hedge_direction_is_opposite_the_drift():
    long_book = aggregate_portfolio([_option("SPY250919C00450000", "SPY", 1, 0.60)], {"SPY": 450.0})
    short_book = aggregate_portfolio([_option("SPY250919P00450000", "SPY", 1, -0.60)], {"SPY": 450.0})
    assert compute_hedge_intents(long_book, RiskEnvelope(), buying_power=1e6, market_open=True)[0].side == "sell"
    assert compute_hedge_intents(short_book, RiskEnvelope(), buying_power=1e6, market_open=True)[0].side == "buy"


def test_drift_below_threshold_does_not_hedge():
    book = aggregate_portfolio([_equity("SPY", 0.4, 450.0)], {"SPY": 450.0})
    assert compute_hedge_intents(book, RiskEnvelope(delta_drift_threshold=1.0), buying_power=1e6, market_open=True) == []


def test_drift_at_threshold_does_hedge():
    """The rule is |Δ| >= 1.0, so exactly 1.0 must fire."""
    book = aggregate_portfolio([_equity("SPY", 1.0, 450.0)], {"SPY": 450.0})
    assert len(compute_hedge_intents(book, RiskEnvelope(), buying_power=1e6, market_open=True)) == 1


def test_hedges_are_ordered_by_severity():
    positions = [_option("SPY250919C00450000", "SPY", 1, 0.20), _option("NVDA250919C00140000", "NVDA", 5, 0.80)]
    book = aggregate_portfolio(positions, {"SPY": 450.0, "NVDA": 140.0})
    intents = compute_hedge_intents(book, RiskEnvelope(), buying_power=1e6, market_open=True)
    assert [i.underlying for i in intents] == ["NVDA", "SPY"]


def test_theta_and_vega_exposures_scale_by_contracts():
    book = aggregate_portfolio([_option("SPY250919C00450000", "SPY", 4, 0.5, theta=-0.05, vega=0.30)], {"SPY": 450.0})
    assert book.net_theta == pytest.approx(-0.05 * 4 * 100)
    assert book.net_vega == pytest.approx(0.30 * 4 * 100)


# --------------------------------------------------------------------------- #
# Shock simulation
# --------------------------------------------------------------------------- #
def _real_option(qty=1):
    """A contract whose Greeks come from the real pricer, not a stub."""
    occ = parse_occ("SPY261218C00450000")
    g = bs_greeks(450.0, occ.strike, occ.year_fraction(), R, 0.20, True)
    return PositionSnapshot(
        symbol=occ.symbol,
        underlying="SPY",
        asset_class="us_option",
        qty=qty,
        market_value=g.price * qty * 100,
        unrealized_pl=0.0,
        avg_entry_price=g.price,
        current_price=g.price,
        greeks=g,
    )


def test_shock_moves_spot_and_repricing_is_real():
    pos = _real_option()
    shocked, spots = apply_price_shock([pos], {"SPY": 0.02}, {"SPY": 450.0}, R)
    assert spots["SPY"] == pytest.approx(459.0)
    assert shocked[0].greeks.price > pos.greeks.price          # long call gains
    assert shocked[0].greeks.delta > pos.greeks.delta          # gamma raises delta
    assert shocked[0].greeks.iv == pytest.approx(pos.greeks.iv)  # sticky strike


def test_shock_drives_delta_past_the_threshold_and_triggers_a_hedge():
    """The end-to-end demonstration: shock -> gamma -> drift -> hedge order."""
    pos = _real_option(qty=1)
    hedge_shares = -pos.greeks.delta * 100
    neutral = [pos, _equity("SPY", hedge_shares, 450.0)]
    book = aggregate_portfolio(neutral, {"SPY": 450.0})
    assert abs(book.net_delta) < 1e-9

    shocked, spots = apply_price_shock(neutral, {"SPY": 0.02}, {"SPY": 450.0}, R)
    shocked_book = aggregate_portfolio(shocked, spots)
    assert abs(shocked_book.net_delta) >= 1.0

    intent = compute_hedge_intents(shocked_book, RiskEnvelope(), buying_power=1e6, market_open=True)[0]
    # Whole-share rounding on the short leg leaves under one delta of residual.
    assert intent.side == "sell" and abs(intent.projected_delta_after) < 1.0


def test_negative_shock_is_symmetric():
    pos = _real_option()
    down, spots = apply_price_shock([pos], {"SPY": -0.02}, {"SPY": 450.0}, R)
    assert spots["SPY"] == pytest.approx(441.0)
    assert down[0].greeks.delta < pos.greeks.delta


def test_zero_shock_is_a_no_op():
    pos = _real_option()
    same, spots = apply_price_shock([pos], {"SPY": 0.0}, {"SPY": 450.0}, R)
    assert same[0] is pos and spots["SPY"] == 450.0


def test_shock_reprices_equity_linearly():
    eq = _equity("SPY", 10.0, 450.0)
    shocked, _ = apply_price_shock([eq], {"SPY": 0.02}, {"SPY": 450.0}, R)
    assert shocked[0].current_price == pytest.approx(459.0)
    assert shocked[0].market_value == pytest.approx(4590.0)


def test_shock_leaves_unshocked_underlyings_untouched():
    positions = [_real_option(), _equity("QQQ", 10.0, 400.0)]
    shocked, spots = apply_price_shock(positions, {"SPY": 0.03}, {"SPY": 450.0, "QQQ": 400.0}, R)
    assert spots["QQQ"] == 400.0
    assert shocked[1] is positions[1]


# --------------------------------------------------------------------------- #
# Broker-acceptance constraints
#
# These encode two rules that live outside our own maths and that a stub broker
# cannot enforce, so they were invisible until the execution path was audited:
# the OPRA price grid, and Alpaca's refusal of fractional short sales.
# --------------------------------------------------------------------------- #
from app.broker import option_tick, round_to_tick  # noqa: E402
from app.quant.hedge_engine import hedge_quantity  # noqa: E402


@pytest.mark.parametrize("price,tick", [(0.05, 0.01), (2.99, 0.01), (3.00, 0.05), (91.74, 0.05)])
def test_opra_tick_size_switches_at_three_dollars(price, tick):
    assert option_tick(price) == tick


@pytest.mark.parametrize("price", [0.07, 1.23, 2.99, 3.00, 8.13, 91.74, 95.31, 420.07])
def test_rounded_limits_land_on_the_grid(price):
    """A limit off the increment grid is rejected by the exchange."""
    for up in (True, False):
        snapped = round_to_tick(price, up=up)
        tick = option_tick(snapped)
        assert abs(round(snapped / tick) - snapped / tick) < 1e-6


def test_buy_limits_round_up_and_sell_limits_round_down():
    """Rounding must preserve marketability, not fight it."""
    assert round_to_tick(91.74, up=True) == pytest.approx(91.75)
    assert round_to_tick(91.74, up=False) == pytest.approx(91.70)


def test_limits_never_round_below_one_tick():
    assert round_to_tick(0.001, up=False) >= 0.01


def test_hedge_never_creates_a_fractional_short():
    """Alpaca accepts fractional longs but rejects fractional short sales.

    A long call hedged from a flat book is exactly this case, so getting it
    wrong breaks the very first hedge the agent ever attempts.
    """
    for net, held in [(48.372, 0.0), (1.5, 0.0), (48.372, 10.0), (200.7, 0.25)]:
        qty = hedge_quantity(net, held)
        resulting = held - qty
        if resulting < 0:
            assert resulting == pytest.approx(round(resulting)), (
                f"net={net} held={held} left a fractional short of {resulting}"
            )


def test_hedge_keeps_fractional_precision_when_buying():
    assert hedge_quantity(-48.372, 0.0) == pytest.approx(48.372)


def test_hedge_keeps_fractional_precision_when_selling_out_of_a_long():
    assert hedge_quantity(10.5, 25.0) == pytest.approx(10.5)


def test_sub_share_short_hedge_rounds_to_zero_and_is_skipped():
    """Under one share of residual delta is inside the drift cap anyway."""
    assert hedge_quantity(0.6, 0.0) == 0.0


def test_whole_share_rounding_never_overshoots_into_a_bigger_short():
    """Rounding is toward zero, so the hedge under-corrects rather than over."""
    for net in (1.9, 12.4, 48.9):
        qty = hedge_quantity(net, 0.0)
        assert qty <= net


def test_residual_delta_after_whole_share_rounding_stays_inside_the_cap():
    for net in (1.2, 5.7, 48.372, 133.99):
        residual = net - hedge_quantity(net, 0.0)
        assert abs(residual) < 1.0


# --------------------------------------------------------------------------- #
# Error reporting
#
# A live preflight showed Alpaca rejecting a fractional short sale with a 403,
# which the handler reported as "rejected these credentials" — on keys that had
# just succeeded twice in the same request. Misdiagnosing an operational refusal
# as an auth failure sends an operator chasing a problem that does not exist.
# --------------------------------------------------------------------------- #
from app.broker import _friendly_api_error  # noqa: E402


class _FakeAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        return self.args[0]


def test_401_reports_a_credential_problem():
    msg = _friendly_api_error(_FakeAPIError("unauthorized", 401))
    assert "credentials" in msg.lower()


def test_403_never_claims_the_credentials_are_bad():
    """The keys are valid; the action is not permitted. Different problem."""
    msg = _friendly_api_error(_FakeAPIError("fractional short selling is not supported", 403))
    assert "credential" not in msg.lower()


def test_403_carries_alpacas_own_words_through():
    raw = "fractional short selling is not supported"
    assert raw in _friendly_api_error(_FakeAPIError(raw, 403))


def test_403_names_the_fractional_short_cause():
    msg = _friendly_api_error(_FakeAPIError("fractional short selling is not supported", 403))
    assert "whole number" in msg.lower()


def test_403_names_the_options_level_cause():
    msg = _friendly_api_error(_FakeAPIError("options level 3 required", 403))
    assert "options level" in msg.lower()


def test_unrecognised_403_still_surfaces_the_payload():
    raw = "some brand new restriction nobody anticipated"
    msg = _friendly_api_error(_FakeAPIError(raw, 403))
    assert raw in msg and "403" in msg


def test_options_wording_without_a_403_is_not_misreported_as_a_level_problem():
    """Precedence bug: `"a" in t or "b" in t and code == 403` binds as
    `"a" in t or ("b" in t and ...)`, so any text mentioning options trading
    triggered the level hint regardless of status code."""
    msg = _friendly_api_error(_FakeAPIError("options trading halted for this symbol", 503))
    assert "not approved for the requested options level" not in msg


def test_unknown_errors_pass_through_verbatim():
    assert _friendly_api_error(_FakeAPIError("kaboom", 500)) == "kaboom"


def test_a_hedge_order_never_crosses_from_long_to_short():
    """Alpaca refuses a single order that sells through zero into a short.

    Reasoning about the resulting position being whole is not sufficient: the
    order itself is a short sale in full, so a fractional quantity is rejected.
    Observed live as 40310000 insufficient buying power while selling 48.295
    against a 41.295 long.
    """
    qty = hedge_quantity(net_delta=48.966, equity_held=41.295)
    assert qty == pytest.approx(41.295), "order crossed zero"
    assert 41.295 - qty == pytest.approx(0.0), "should land exactly flat"


def test_the_short_is_opened_on_the_following_cycle_from_flat():
    """Having flattened, the remaining exposure becomes a clean whole-share short."""
    remaining = 48.966 - 41.295
    qty = hedge_quantity(net_delta=remaining, equity_held=0.0)
    assert qty == pytest.approx(7.0)
    assert qty % 1 == 0


def test_buying_through_zero_is_capped_at_the_short_size():
    """Symmetric to the sell case, and the assertion that was too weak.

    Covering a 12-share short with a 30-share buy would leave 18 long — the
    order crosses zero and Alpaca refuses it as "insufficient qty available".
    The earlier version asserted `qty <= 30.0`, which the buggy code satisfied
    trivially, so the bug shipped and surfaced live at 50.516 against 50.
    """
    qty = hedge_quantity(net_delta=-30.0, equity_held=-12.0)
    assert qty == pytest.approx(12.0), "buy crossed zero"
    assert -12.0 + qty == pytest.approx(0.0), "should land exactly flat"


def test_the_long_is_opened_on_the_following_cycle_from_flat():
    remaining = 30.0 - 12.0
    assert hedge_quantity(net_delta=-remaining, equity_held=0.0) == pytest.approx(18.0)


def test_buying_to_partially_cover_a_short_keeps_precision():
    """Not crossing zero, so fractional stands."""
    assert hedge_quantity(net_delta=-5.5, equity_held=-20.0) == pytest.approx(5.5)


@pytest.mark.parametrize(
    "held,net",
    [(-50.0, -50.516), (-12.0, -30.0), (0.0, -7.3), (-20.0, -5.5), (41.295, 48.966), (10.0, 25.5)],
)
def test_no_hedge_order_crosses_zero_in_either_direction(held, net):
    qty = hedge_quantity(net, held)
    resulting = held + (qty if net < 0 else -qty)
    if held > 0:
        assert resulting >= -1e-9, f"sell crossed zero: {held} -> {resulting}"
    elif held < 0:
        assert resulting <= 1e-9, f"buy crossed zero: {held} -> {resulting}"


@pytest.mark.parametrize("held,net", [(41.295, 48.966), (10.0, 25.5), (0.5, 3.2), (100.0, 100.7)])
def test_no_hedge_order_ever_flips_the_sign_of_the_position(held, net):
    qty = hedge_quantity(net, held)
    resulting = held - qty
    assert resulting >= -1e-9 or held <= 0, (
        f"held={held} qty={qty} would cross zero to {resulting}"
    )


def test_quantity_available_is_not_reported_as_a_funding_problem():
    """Alpaca reuses 40310000 for two unrelated causes.

    "insufficient qty available" means the order asked for more than the
    position can supply — an order crossing zero — not that the account is
    short of capital. Reporting it as a buying-power problem sends an operator
    to check funding, which was fine, while the real cause is the order size.
    """
    raw = '{"code":40310000,"message":"insufficient qty available for order (requested: 3, available: 2)"}'
    msg = _friendly_api_error(_FakeAPIError(raw, 403))
    assert "cross from long to short" in msg
    assert "Insufficient buying power" not in msg
    assert raw in msg, "Alpaca's payload must still carry through"


def test_a_genuine_funding_shortfall_still_reports_buying_power():
    msg = _friendly_api_error(_FakeAPIError("insufficient buying power", 403))
    assert "buying power" in msg.lower()
