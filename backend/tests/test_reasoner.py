"""Decision-rule and prompt-construction tests.

No network. These cover the boundary between "what the mandate says" and "what
the model is told", which is where a live regression went unnoticed: the model
was handed a prose mandate, read IV rank 25 with implied vol 13.7 points below
realised, and held — the textbook long-volatility setup, declined.

The fix was to compute the signal deterministically and hand it over. These
tests keep the prompt and the fallback reading the same thresholds.
"""

from __future__ import annotations

import pytest

from app.agents.reasoner import _attach_baseline, build_user_prompt, deterministic_policy
from app.broker import VolProfile
from app.quant.risk_gate import RiskEnvelope
from app.state_store import Strategy

from .test_tools import make_contract


def profile(underlying: str, rank: float | None, premium: float | None = 0.0) -> VolProfile:
    return VolProfile(
        underlying=underlying,
        spot=100.0,
        atm_iv=0.25,
        realized_vol_20d=0.25,
        iv_rank=rank,
        iv_premium=premium,
        sample_size=255,
    )


# --------------------------------------------------------------------------- #
# Thresholds
# --------------------------------------------------------------------------- #
def envelope_for(strategy: Strategy) -> RiskEnvelope:
    sell_at, buy_at = strategy.thresholds
    return RiskEnvelope(iv_rank_sell_at=sell_at, iv_rank_buy_at=buy_at)


@pytest.mark.parametrize(
    "strategy,rank,expected",
    [
        # Adaptive VRP: sell >= 65, buy <= 35, hold between.
        (Strategy.ADAPTIVE_VRP, 84, "sell"),
        (Strategy.ADAPTIVE_VRP, 65, "sell"),
        (Strategy.ADAPTIVE_VRP, 64.9, None),
        (Strategy.ADAPTIVE_VRP, 50, None),
        (Strategy.ADAPTIVE_VRP, 35.1, None),
        (Strategy.ADAPTIVE_VRP, 35, "buy"),
        # The live regression: rank 25 must buy, not hold.
        (Strategy.ADAPTIVE_VRP, 25, "buy"),
        (Strategy.ADAPTIVE_VRP, 0, "buy"),
        # Income only ever sells.
        (Strategy.DELTA_NEUTRAL_INCOME, 60, "sell"),
        (Strategy.DELTA_NEUTRAL_INCOME, 59.9, None),
        (Strategy.DELTA_NEUTRAL_INCOME, 5, None),
        # Long vol only ever buys.
        (Strategy.LONG_VOL_CONVEXITY, 40, "buy"),
        (Strategy.LONG_VOL_CONVEXITY, 40.1, None),
        (Strategy.LONG_VOL_CONVEXITY, 95, None),
    ],
)
def test_signal_boundaries(strategy, rank, expected):
    assert envelope_for(strategy).signal_for(rank) == expected


def test_unknown_rank_produces_no_signal():
    for strategy in Strategy:
        assert envelope_for(strategy).signal_for(None) is None


def test_decision_rule_states_every_threshold_numerically():
    """The prompt must contain the numbers, not adjectives."""
    for strategy in Strategy:
        env = envelope_for(strategy)
        rule = env.decision_rule
        if env.iv_rank_sell_at is not None:
            assert f">= {env.iv_rank_sell_at:.0f}" in rule
        if env.iv_rank_buy_at is not None:
            assert f"<= {env.iv_rank_buy_at:.0f}" in rule


def test_operator_thresholds_override_the_strategy_default():
    """The dials belong to the operator, not to the code."""
    strict = RiskEnvelope(iv_rank_sell_at=90.0, iv_rank_buy_at=10.0)
    assert strict.signal_for(84) is None      # would fire on the 65 default
    assert strict.signal_for(25) is None      # would fire on the 35 default
    assert strict.signal_for(92) == "sell"
    assert strict.signal_for(5) == "buy"


def test_a_side_can_be_disabled_entirely():
    sell_only = RiskEnvelope(iv_rank_sell_at=60.0, iv_rank_buy_at=None)
    assert sell_only.signal_for(5) is None
    assert sell_only.signal_for(70) == "sell"


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def _prompt(strategy, profiles, candidates, envelope=None):
    return build_user_prompt(
        strategy=strategy,
        envelope=envelope or envelope_for(strategy),
        vol_profiles=profiles,
        candidates=candidates,
        net_delta=0.0,
        open_positions=0,
        max_positions=6,
        buying_power=100_000.0,
        day_pnl=0.0,
    )


def test_prompt_shows_the_baseline_reading_per_underlying():
    text = _prompt(
        Strategy.ADAPTIVE_VRP,
        [profile("NVDA", 25, -0.137)],
        [make_contract(underlying="NVDA")],
    )
    assert "BASELINE: BUY" in text
    assert "baseline buy" in text


def test_prompt_invites_disagreement_rather_than_forbidding_it():
    """The model decides. The baseline is an opinion, not an order."""
    text = _prompt(
        Strategy.ADAPTIVE_VRP,
        [profile("NVDA", 25, -0.137)],
        [make_contract(underlying="NVDA")],
    )
    assert "Decide for yourself" in text
    assert "HOLD is not an acceptable answer" not in text


def test_prompt_says_when_the_baseline_sees_nothing():
    text = _prompt(
        Strategy.ADAPTIVE_VRP,
        [profile("SPY", 50, 0.01), profile("QQQ", 46, 0.0)],
        [make_contract(underlying="SPY")],
    )
    assert "no edge in any underlying" in text


def test_prompt_marks_candidates_with_no_baseline_edge():
    text = _prompt(
        Strategy.ADAPTIVE_VRP,
        [profile("SPY", 50)],
        [make_contract(underlying="SPY")],
    )
    assert "baseline flat" in text


def test_prompt_separates_baselines_per_underlying():
    text = _prompt(
        Strategy.ADAPTIVE_VRP,
        [profile("NVDA", 25, -0.10), profile("AAPL", 80, 0.09), profile("SPY", 50)],
        [make_contract(underlying="NVDA"), make_contract(underlying="AAPL")],
    )
    assert "NVDA (buy)" in text and "AAPL (sell)" in text


# --------------------------------------------------------------------------- #
# Deterministic fallback agrees with the stated rule
# --------------------------------------------------------------------------- #
def test_fallback_buys_the_low_rank_case_the_model_previously_held():
    decision = deterministic_policy(
        Strategy.ADAPTIVE_VRP,
        [profile("NVDA", 25, -0.137)],
        [make_contract(underlying="NVDA")],
        max_contracts=1,
        envelope=envelope_for(Strategy.ADAPTIVE_VRP),
    )
    assert decision.action == "OPEN"
    assert decision.side == "buy"


def test_fallback_sells_a_rich_rank():
    decision = deterministic_policy(
        Strategy.ADAPTIVE_VRP,
        [profile("AAPL", 84, 0.09)],
        [make_contract(underlying="AAPL")],
        max_contracts=1,
    )
    assert decision.action == "OPEN" and decision.side == "sell"


def test_fallback_holds_inside_the_neutral_band():
    decision = deterministic_policy(
        Strategy.ADAPTIVE_VRP,
        [profile("SPY", 50, 0.01)],
        [make_contract(underlying="SPY")],
        max_contracts=1,
    )
    assert decision.action == "HOLD"


@pytest.mark.parametrize("strategy", list(Strategy))
@pytest.mark.parametrize("rank", [0, 25, 35, 50, 60, 65, 84, 100])
def test_fallback_never_contradicts_the_stated_rule(strategy, rank):
    """Whatever the fallback does must match the rule printed in the prompt."""
    decision = deterministic_policy(
        strategy,
        [profile("SPY", rank)],
        [make_contract(underlying="SPY")],
        max_contracts=1,
    )
    expected = envelope_for(strategy).signal_for(rank)
    if expected is None:
        assert decision.action == "HOLD"
    else:
        assert decision.action == "OPEN" and decision.side == expected


def test_fallback_holds_when_there_are_no_candidates():
    decision = deterministic_policy(Strategy.ADAPTIVE_VRP, [profile("SPY", 20)], [], 1)
    assert decision.action == "HOLD" and decision.contracts == 0


def test_fallback_respects_the_contract_ceiling():
    decision = deterministic_policy(
        Strategy.ADAPTIVE_VRP,
        [profile("NVDA", 10, -0.2)],
        [make_contract(underlying="NVDA")],
        max_contracts=5,
    )
    assert 1 <= decision.contracts <= 5


# --------------------------------------------------------------------------- #
# Divergence recording
# --------------------------------------------------------------------------- #
def _decision(action, symbol=None, side="buy", source="featherless"):
    from app.agents.reasoner import Decision

    return Decision(
        action=action,
        symbol=symbol,
        side=side,
        contracts=1,
        confidence=0.7,
        thesis="",
        source=source,
    )


def test_agreement_is_not_flagged_as_divergence():
    model = _decision("OPEN", "SPY261001C00450000", "buy")
    baseline = _decision("OPEN", "SPY261001C00450000", "buy", "deterministic")
    assert _attach_baseline(model, baseline).diverged is False


def test_opposite_action_is_flagged():
    model = _decision("HOLD")
    baseline = _decision("OPEN", "NVDA261001C00450000", "buy", "deterministic")
    result = _attach_baseline(model, baseline)
    assert result.diverged is True
    assert "HOLD" in result.divergence and "OPEN" in result.divergence


def test_opposite_side_is_flagged():
    model = _decision("OPEN", "SPY261001C00450000", "sell")
    baseline = _decision("OPEN", "SPY261001C00450000", "buy", "deterministic")
    result = _attach_baseline(model, baseline)
    assert result.diverged is True
    assert "sell" in result.divergence and "buy" in result.divergence


def test_different_contract_same_direction_is_flagged_softly():
    model = _decision("OPEN", "SPY261001C00450000", "buy")
    baseline = _decision("OPEN", "SPY261001C00455000", "buy", "deterministic")
    result = _attach_baseline(model, baseline)
    assert result.diverged is True
    assert "different contract" in result.divergence


def test_baseline_is_always_recorded_even_on_agreement():
    model = _decision("OPEN", "SPY261001C00450000", "buy")
    baseline = _decision("OPEN", "SPY261001C00450000", "buy", "deterministic")
    result = _attach_baseline(model, baseline)
    assert result.baseline_action == "OPEN"
    assert result.baseline_side == "buy"
    assert result.as_dict()["baseline_symbol"] == "SPY261001C00450000"
