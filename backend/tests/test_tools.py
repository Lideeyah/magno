"""End-to-end tests of the agent's tool surface against a stub broker.

These exercise the real ``MagnoTools`` code path — the same one the autonomous
loop and the MCP server call — with Alpaca replaced by an in-memory double. That
covers the parts unit tests cannot reach: that a vetoed order is never
submitted, that an approved one is, that hedges size and direct themselves
correctly, and that an active shock suppresses live submission.

    cd backend && .venv/bin/python -m pytest tests -q
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import pytest

from app.agents.alpaca_mcp import MagnoTools
from app.broker import AccountSnapshot, BrokerError, ChainContract
from app.config import settings
from app.events import AuditLog
from app.quant.greeks import bs_greeks, parse_occ
from app.quant.hedge_engine import PositionSnapshot
from app.quant.risk_gate import RiskEnvelope
from app.state_store import SessionState, Strategy

SPOT = 450.0


def occ_symbol(strike: float, dte: int, right: str = "C", root: str = "SPY") -> str:
    expiry = date.today() + timedelta(days=dte)
    return f"{root}{expiry:%y%m%d}{right}{int(round(strike * 1000)):08d}"


@dataclass
class StubBroker:
    """Minimal stand-in for AlpacaBroker with recording order methods."""

    positions: list[PositionSnapshot] = field(default_factory=list)
    spots: dict[str, float] = field(default_factory=lambda: {"SPY": SPOT})
    market_open: bool = True
    equity: float = 100_000.0
    last_equity: float = 100_000.0
    buying_power: float = 200_000.0
    chain: list[ChainContract] = field(default_factory=list)
    equity_orders: list[dict] = field(default_factory=list)
    option_orders: list[dict] = field(default_factory=list)
    fail_option_order: str | None = None
    # Share-equivalent delta already resting at the broker, per symbol. Lets a
    # test reproduce the condition that caused the live hedge runaway.
    in_flight: dict[str, float] = field(default_factory=dict)

    async def get_account(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="stub-account",
            account_number="PA0000STUB",
            status="ACTIVE",
            equity=self.equity,
            last_equity=self.last_equity,
            cash=self.equity,
            buying_power=self.buying_power,
            options_buying_power=self.buying_power,
            portfolio_value=self.equity,
            long_market_value=0.0,
            short_market_value=0.0,
            options_trading_level=3,
            pattern_day_trader=False,
            trading_blocked=False,
        )

    async def is_market_open(self) -> bool:
        return self.market_open

    async def get_positions(self) -> list[PositionSnapshot]:
        return list(self.positions)

    async def get_spots(self, symbols) -> dict[str, float]:
        return {s: self.spots[s] for s in symbols if s in self.spots}

    async def get_chain(self, underlying, **kwargs) -> list[ChainContract]:
        return [c for c in self.chain if c.underlying == underlying.upper()]

    async def in_flight_equity_delta(self) -> dict[str, float]:
        return dict(self.in_flight)

    async def get_open_orders(self) -> list[dict]:
        return []

    async def submit_equity_order(self, symbol, qty, side, client_order_id=None) -> dict:
        order = {"id": f"eq-{len(self.equity_orders)}", "symbol": symbol, "qty": qty,
                 "side": side, "status": "filled", "filled_qty": qty,
                 "filled_avg_price": self.spots.get(symbol, SPOT)}
        self.equity_orders.append(order)
        return order

    async def submit_option_order(
        self, symbol, qty, side, limit_price=None, client_order_id=None
    ) -> dict:
        if self.fail_option_order:
            raise BrokerError(self.fail_option_order)
        order = {
            "id": f"opt-{len(self.option_orders)}",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "limit_price": limit_price,
        }
        self.option_orders.append(order)
        return order


def make_contract(
    *,
    strike: float = 450.0,
    dte: int = 30,
    right: str = "C",
    bid: float = 8.00,
    ask: float = 8.10,
    open_interest: int | None = 5_000,
    underlying: str = "SPY",
) -> ChainContract:
    symbol = occ_symbol(strike, dte, right, underlying)
    occ = parse_occ(symbol)
    assert occ is not None
    mid = (bid + ask) / 2
    # A contract with no two-sided quote is a real state — an illiquid wing, a
    # halted series — so the helper must be able to represent one.
    spread = ((ask - bid) / mid) if mid > 0 else None
    greeks = bs_greeks(SPOT, strike, occ.year_fraction(), settings.risk_free_rate, 0.20, right == "C")
    return ChainContract(
        symbol=symbol,
        underlying=underlying,
        right=right,
        strike=strike,
        expiry=occ.expiry.isoformat(),
        dte=occ.days_to_expiry(),
        bid=bid or None,
        ask=ask or None,
        mid=mid or None,
        last=mid or None,
        spread_pct=spread,
        open_interest=open_interest,
        iv=0.20,
        iv_source="magno_bsm",
        greeks=greeks,
        greeks_source="magno_bsm",
        spot=SPOT,
        tradable=True,
        moneyness=strike / SPOT - 1.0,
    )


def make_session(broker: StubBroker, **envelope_overrides) -> SessionState:
    return SessionState(
        session_id="test",
        broker=broker,  # type: ignore[arg-type]
        envelope=RiskEnvelope(**envelope_overrides),
        strategy=Strategy.ADAPTIVE_VRP,
        audit=AuditLog(),
        account=None,  # type: ignore[arg-type]
        created_at=datetime.now(timezone.utc),
        equity_at_open=100_000.0,
        contract_qty=1,
    )


def option_position(contract: ChainContract, qty: int) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=contract.symbol,
        underlying=contract.underlying,
        asset_class="us_option",
        qty=qty,
        market_value=(contract.mid or 0) * qty * 100,
        unrealized_pl=0.0,
        avg_entry_price=contract.mid or 0,
        current_price=contract.mid or 0,
        greeks=contract.greeks,
    )


def equity_position(underlying: str, qty: float, price: float = SPOT) -> PositionSnapshot:
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


# --------------------------------------------------------------------------- #
# execute_options_strategy
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_clean_order_is_submitted():
    contract = make_contract()
    broker = StubBroker(chain=[contract])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)

    assert result["submitted"] is True
    assert len(broker.option_orders) == 1
    assert broker.option_orders[0]["symbol"] == contract.symbol
    assert result["gate"]["approved"] is True


@pytest.mark.asyncio
async def test_order_is_priced_as_a_marketable_limit_not_market():
    """A naked market order on a thin options book is uncontrolled slippage."""
    contract = make_contract(bid=8.00, ask=8.10)
    broker = StubBroker(chain=[contract])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)

    from app.broker import option_tick

    limit = result["limit_price"]
    assert limit is not None
    # Crosses fully to the offer plus one tick, so it actually fills, and no
    # further — slippage is capped at the displayed NBBO.
    assert limit >= contract.ask
    assert limit <= contract.ask + option_tick(contract.ask) + 1e-9


@pytest.mark.asyncio
async def test_sell_limit_crosses_down_to_the_bid():
    contract = make_contract(bid=8.00, ask=8.10)
    broker = StubBroker(chain=[contract])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "sell", 1)
    assert result["limit_price"] <= contract.bid


@pytest.mark.asyncio
async def test_wide_spread_order_is_vetoed_and_never_submitted():
    contract = make_contract(bid=8.00, ask=9.20)  # ~14% spread
    broker = StubBroker(chain=[contract])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)

    assert result["submitted"] is False
    assert broker.option_orders == []
    assert "SPREAD_TOO_WIDE" in {c["code"] for c in result["gate"]["checks"]}


@pytest.mark.asyncio
async def test_market_closed_blocks_execution():
    contract = make_contract()
    broker = StubBroker(chain=[contract], market_open=False)
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)
    assert result["submitted"] is False and broker.option_orders == []


@pytest.mark.asyncio
async def test_oversized_order_is_vetoed_by_the_allocation_cap():
    contract = make_contract()
    broker = StubBroker(chain=[contract], buying_power=20_000.0)
    tools = MagnoTools(make_session(broker))

    # 50 contracts x $8.05 x 100 = $40,250 against $20k buying power.
    result = await tools.execute_options_strategy(contract.symbol, "buy", 50)

    assert result["submitted"] is False
    assert "ALLOC_EXCEEDS_CAP" in {c["code"] for c in result["gate"]["checks"]}


@pytest.mark.asyncio
async def test_loss_breaker_blocks_new_risk():
    contract = make_contract()
    broker = StubBroker(chain=[contract], equity=93_000.0, last_equity=100_000.0)
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)

    assert result["submitted"] is False
    assert "DAILY_LOSS_HALT" in {c["code"] for c in result["gate"]["checks"]}


@pytest.mark.asyncio
async def test_malformed_symbol_is_rejected_before_any_broker_call():
    broker = StubBroker()
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy("NOT-AN-OCC-SYMBOL", "buy", 1)

    assert result["submitted"] is False
    assert "not a valid OCC" in result["error"]
    assert broker.option_orders == []


@pytest.mark.asyncio
async def test_unquotable_symbol_is_rejected():
    broker = StubBroker(chain=[])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(occ_symbol(450, 30), "buy", 1)

    assert result["submitted"] is False
    assert "No live quote" in result["error"]


@pytest.mark.asyncio
async def test_force_does_not_bypass_the_gates():
    """`force` marks an order operator-initiated; it grants no exemptions."""
    contract = make_contract(bid=8.00, ask=9.20)
    broker = StubBroker(chain=[contract])
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1, force=True)
    assert result["submitted"] is False and broker.option_orders == []


@pytest.mark.asyncio
async def test_broker_failure_is_surfaced_not_swallowed():
    contract = make_contract()
    broker = StubBroker(chain=[contract], fail_option_order="insufficient options level")
    tools = MagnoTools(make_session(broker))

    result = await tools.execute_options_strategy(contract.symbol, "buy", 1)
    assert result["submitted"] is False
    assert "insufficient options level" in result["error"]


@pytest.mark.asyncio
async def test_stale_candidate_is_repriced_against_a_live_quote():
    """A candidate captured when the book was tight must be re-gated at submit
    time against the current, now-wide, quote."""
    stale = make_contract(bid=8.00, ask=8.10)
    live = make_contract(bid=8.00, ask=9.20)
    broker = StubBroker(chain=[live])
    tools = MagnoTools(make_session(broker))

    # The caller passes a mismatched symbol so the tool must refetch.
    result = await tools.execute_options_strategy(
        live.symbol, "buy", 1, contract=make_contract(strike=455.0)
    )

    assert result["submitted"] is False
    assert "SPREAD_TOO_WIDE" in {c["code"] for c in result["gate"]["checks"]}
    assert stale.symbol == live.symbol  # same contract, different book


# --------------------------------------------------------------------------- #
# rebalance_portfolio
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_neutral_book_is_not_hedged():
    contract = make_contract()
    hedge_shares = -contract.greeks.delta * 100
    broker = StubBroker(
        positions=[option_position(contract, 1), equity_position("SPY", hedge_shares)]
    )
    tools = MagnoTools(make_session(broker))

    result = await tools.rebalance_portfolio()

    assert result["hedged"] is False
    assert broker.equity_orders == []
    assert "inside the" in result["reason"]


@pytest.mark.asyncio
async def test_long_delta_is_hedged_by_selling_shares():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)])
    tools = MagnoTools(make_session(broker))

    result = await tools.rebalance_portfolio()

    assert result["hedged"] is True
    assert len(broker.equity_orders) == 1
    order = broker.equity_orders[0]
    assert order["side"] == "sell"
    assert order["symbol"] == "SPY"
    # Short leg, so whole shares; under-corrects by less than one delta.
    exact = contract.greeks.delta * 100
    assert order["qty"] == pytest.approx(float(int(exact)))
    assert 0 <= exact - order["qty"] < 1.0


@pytest.mark.asyncio
async def test_short_delta_is_hedged_by_buying_shares():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, -1)])
    tools = MagnoTools(make_session(broker))

    await tools.rebalance_portfolio()

    assert broker.equity_orders[0]["side"] == "buy"


@pytest.mark.asyncio
async def test_hedge_is_fractional_when_the_broker_permits_it():
    """A short option needs a *long* equity hedge, which Alpaca does accept
    fractionally — so precision must be preserved there."""
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, -1)])
    tools = MagnoTools(make_session(broker))

    await tools.rebalance_portfolio()

    order = broker.equity_orders[0]
    assert order["side"] == "buy"
    assert order["qty"] % 1 != 0, "fractional precision lost on a hedge that allows it"


@pytest.mark.asyncio
async def test_short_hedge_is_never_fractional():
    """The regression that would have broken the first live hedge."""
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)])
    tools = MagnoTools(make_session(broker))

    await tools.rebalance_portfolio()

    order = broker.equity_orders[0]
    assert order["side"] == "sell"
    assert order["qty"] % 1 == 0, "submitted a fractional short sale; Alpaca rejects these"


@pytest.mark.asyncio
async def test_hedge_does_not_fire_when_market_is_closed():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)], market_open=False)
    tools = MagnoTools(make_session(broker))

    result = await tools.rebalance_portfolio()

    assert broker.equity_orders == []
    assert any(not e["submitted"] for e in result["executed"])


@pytest.mark.asyncio
async def test_force_hedges_below_the_drift_cap():
    broker = StubBroker(positions=[equity_position("SPY", 0.4)])
    tools = MagnoTools(make_session(broker))

    assert (await tools.rebalance_portfolio())["hedged"] is False
    assert (await tools.rebalance_portfolio(force=True))["hedged"] is True
    assert broker.equity_orders[0]["side"] == "sell"


@pytest.mark.asyncio
async def test_hedge_continues_after_the_loss_breaker_trips():
    """The breaker stops new risk. Trapping the book long would be worse."""
    contract = make_contract()
    broker = StubBroker(
        positions=[option_position(contract, 1)], equity=90_000.0, last_equity=100_000.0
    )
    tools = MagnoTools(make_session(broker))

    result = await tools.rebalance_portfolio()

    assert result["hedged"] is True
    assert len(broker.equity_orders) == 1


@pytest.mark.asyncio
async def test_each_underlying_is_hedged_separately():
    spy = make_contract(underlying="SPY")
    nvda = make_contract(underlying="NVDA", strike=450.0)
    broker = StubBroker(
        positions=[option_position(spy, 1), option_position(nvda, -1)],
        spots={"SPY": SPOT, "NVDA": SPOT},
    )
    tools = MagnoTools(make_session(broker))

    await tools.rebalance_portfolio()

    by_symbol = {o["symbol"]: o["side"] for o in broker.equity_orders}
    assert by_symbol == {"SPY": "sell", "NVDA": "buy"}


# --------------------------------------------------------------------------- #
# Shock simulation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_shock_creates_drift_but_suppresses_live_submission():
    """A shocked book is hypothetical: the hedge is computed and logged, but
    submitting it would put a real order behind a move that never happened."""
    contract = make_contract()
    hedge_shares = -contract.greeks.delta * 100
    broker = StubBroker(
        positions=[option_position(contract, 1), equity_position("SPY", hedge_shares)]
    )
    state = make_session(broker)
    tools = MagnoTools(state)

    assert (await tools.rebalance_portfolio())["hedged"] is False

    state.shocks["SPY"] = 0.03
    result = await tools.rebalance_portfolio()

    assert result["intents"], "shock did not produce delta drift"
    assert abs(result["net_delta"]) >= state.envelope.delta_drift_threshold
    assert broker.equity_orders == [], "submitted a live order against a simulated price"
    assert all(e.get("simulated") for e in result["executed"])


@pytest.mark.asyncio
async def test_clearing_the_shock_restores_live_hedging():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)])
    state = make_session(broker)
    tools = MagnoTools(state)

    state.shocks["SPY"] = 0.03
    await tools.rebalance_portfolio()
    assert broker.equity_orders == []

    state.shocks.clear()
    assert (await tools.rebalance_portfolio())["hedged"] is True
    assert len(broker.equity_orders) == 1


# --------------------------------------------------------------------------- #
# get_account_greeks
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_account_greeks_reports_aggregated_exposure():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 2)])
    tools = MagnoTools(make_session(broker))

    result = await tools.get_account_greeks()

    assert result["greeks"]["net_delta"] == pytest.approx(contract.greeks.delta * 2 * 100)
    assert result["greeks"]["gross_option_positions"] == 1
    assert result["account"]["equity"] == 100_000.0


# --------------------------------------------------------------------------- #
# Audit trail
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_every_decision_lands_in_the_audit_log():
    contract = make_contract()
    broker = StubBroker(chain=[contract], positions=[option_position(contract, 1)])
    state = make_session(broker)
    tools = MagnoTools(state)

    await tools.execute_options_strategy(contract.symbol, "buy", 1)
    await tools.rebalance_portfolio()

    categories = {e["category"] for e in state.audit.recent(100)}
    assert {"gate", "order", "hedge", "risk"} <= categories


@pytest.mark.asyncio
async def test_rejections_are_logged_with_the_full_gate_transcript():
    contract = make_contract(bid=8.00, ask=9.20)
    broker = StubBroker(chain=[contract])
    state = make_session(broker)

    await MagnoTools(state).execute_options_strategy(contract.symbol, "buy", 1)

    rejects = [e for e in state.audit.recent(50) if e["level"] == "reject"]
    assert rejects, "a vetoed order left no audit record"
    assert rejects[0]["data"]["gate"]["checks"], "gate transcript was not recorded"


# --------------------------------------------------------------------------- #
# In-flight suppression at the tool layer
#
# The pure function is tested in test_exits_and_spreads. This covers the path
# that actually ran away in production: rebalance_portfolio must consult the
# broker for resting orders before submitting, not just trust the position.
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_rebalance_does_not_stack_orders_behind_a_resting_hedge():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)])
    tools = MagnoTools(make_session(broker))

    first = await tools.rebalance_portfolio()
    assert first["hedged"] is True
    submitted = broker.equity_orders[0]["qty"]

    # The fill has not settled: the position is unchanged, but the order rests.
    broker.in_flight["SPY"] = -submitted

    for _ in range(5):
        result = await tools.rebalance_portfolio()
        assert result["hedged"] is False
    assert len(broker.equity_orders) == 1, "stacked duplicate hedges behind a resting order"


@pytest.mark.asyncio
async def test_rebalance_reports_why_it_stood_down():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)], in_flight={"SPY": -53.0})
    result = await MagnoTools(make_session(broker)).rebalance_portfolio()
    assert result["hedged"] is False
    assert "in flight" in result["reason"]


@pytest.mark.asyncio
async def test_rebalance_tops_up_only_the_uncovered_remainder():
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)], in_flight={"SPY": -40.0})
    tools = MagnoTools(make_session(broker))

    result = await tools.rebalance_portfolio()
    assert result["hedged"] is True
    exact = contract.greeks.delta * 100 - 40.0
    assert broker.equity_orders[0]["qty"] <= exact + 1e-9


@pytest.mark.asyncio
async def test_hedge_refuses_to_run_blind_when_open_orders_cannot_be_read():
    """Fail closed. If we cannot tell what is already in flight, adding more is
    exactly how the runaway happened."""
    contract = make_contract()
    broker = StubBroker(positions=[option_position(contract, 1)])

    async def boom():
        raise BrokerError("Alpaca unreachable")

    broker.in_flight_equity_delta = lambda: boom()
    result = await MagnoTools(make_session(broker)).rebalance_portfolio()

    assert result["hedged"] is False
    assert broker.equity_orders == []
    assert "in-flight" in result["reason"]
