"""Magno's tool surface, exposed two ways over one implementation.

``MagnoTools`` is the single definition of what the agent can *do*:

    scan_market_volatility   survey the universe, rank IV, return gate-approved contracts
    get_account_greeks       account, positions and net Δ/Γ/Θ/ν
    execute_options_strategy gate-check then submit an options order
    rebalance_portfolio      neutralise delta drift with fractional equity orders

The autonomous loop calls these methods in-process. The same four are published
as MCP tools over stdio by :func:`build_mcp_server`, so an external MCP client
(Claude Desktop, the Alpaca MCP tooling, an inspector) drives the identical code
path -- including every risk gate. There is no "MCP mode" that bypasses risk,
because there is only one implementation.

Run the MCP server standalone:

    cd backend && .venv/bin/python -m app.agents.alpaca_mcp
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..broker import AlpacaBroker, BrokerError, ChainContract, VolProfile
from ..config import settings
from ..events import EventCategory, EventLevel
from ..quant.hedge_engine import (
    HedgeIntent,
    PortfolioGreeks,
    PositionSnapshot,
    aggregate_portfolio,
    apply_price_shock,
    compute_hedge_intents,
)
from ..quant.risk_gate import GateResult, evaluate_option_order
from ..state_store import SessionState

log = logging.getLogger("magno.tools")


class BookView:
    """A coherent snapshot of the book: positions, spots and aggregate Greeks,
    with any active shock already applied so every consumer sees one reality."""

    def __init__(
        self,
        positions: list[PositionSnapshot],
        spots: dict[str, float],
        book: PortfolioGreeks,
        shocked: bool,
    ) -> None:
        self.positions = positions
        self.spots = spots
        self.book = book
        self.shocked = shocked


async def build_book(state: SessionState) -> BookView:
    """Fetch live positions, apply any active shock, and aggregate Greeks."""
    positions = await state.broker.get_positions()
    underlyings = sorted({p.underlying for p in positions} | set(settings.universe))
    spots = await state.broker.get_spots(underlyings)

    shocked = False
    if state.shocks:
        positions, spots = apply_price_shock(
            positions, state.shocks, spots, settings.risk_free_rate
        )
        shocked = True

    return BookView(positions, spots, aggregate_portfolio(positions, spots), shocked)


class MagnoTools:
    def __init__(self, state: SessionState) -> None:
        self.state = state

    @property
    def broker(self) -> AlpacaBroker:
        return self.state.broker

    # ------------------------------------------------------------------ #
    # Tool 1: scan_market_volatility
    # ------------------------------------------------------------------ #
    async def scan_market_volatility(
        self,
        underlyings: list[str] | None = None,
        *,
        emit: bool = True,
        assume_market_open: bool = False,
    ) -> dict[str, Any]:
        """Survey the universe: IV rank per name, plus every contract that clears
        the pre-trade gates. Rejections are returned too -- the funnel is the
        evidence that the gates are real."""
        names = [u.upper() for u in (underlyings or settings.universe)]
        audit = self.state.audit
        env = self.state.envelope

        account = await self.broker.get_account()
        market_open = await self.broker.is_market_open()
        # A dry run asks "what would the agent do if it could trade", so
        # candidate selection assumes open hours. The real market-hours gate
        # still runs on the resulting order, and still blocks it.
        gate_market_open = True if assume_market_open else market_open
        view = await build_book(self.state)

        profiles: list[VolProfile] = []
        approved: list[ChainContract] = []
        rejected: list[dict] = []
        chain_rows: list[dict] = []
        errors: list[str] = []

        for name in names:
            try:
                atm = await self.broker.atm_iv(name)
                profile = await self.broker.get_vol_profile(name, atm)
                profiles.append(profile)

                chain = await self.broker.get_chain(
                    name, min_dte=env.min_dte, max_dte=env.max_dte, moneyness_band=0.12
                )
            except BrokerError as exc:
                errors.append(f"{name}: {exc}")
                if emit:
                    audit.warn(EventCategory.SCAN, f"{name} scan degraded", str(exc), underlying=name)
                continue

            for contract in chain:
                if not contract.tradable or contract.greeks is None:
                    continue
                gate = evaluate_option_order(
                    bid=contract.bid,
                    ask=contract.ask,
                    iv=contract.iv,
                    dte=contract.dte,
                    open_interest=contract.open_interest,
                    contracts=self.state.contract_qty,
                    buying_power=account.options_buying_power or account.buying_power,
                    open_positions=view.book.gross_option_positions,
                    day_pnl=account.day_pnl,
                    equity_at_open=self.state.equity_at_open,
                    market_open=gate_market_open,
                    envelope=env,
                )
                row = contract.as_dict()
                row["gate"] = gate.as_dict()
                chain_rows.append(row)
                if gate.approved:
                    approved.append(contract)
                else:
                    rejected.append(
                        {"symbol": contract.symbol, "reasons": [c.code for c in gate.rejections]}
                    )

        # Rank the approved set by how far IV rank sits from neutral: the
        # strongest measurable edge, regardless of direction.
        rank_by_name = {p.underlying: (p.iv_rank if p.iv_rank is not None else 50.0) for p in profiles}
        approved.sort(
            key=lambda c: (
                abs(rank_by_name.get(c.underlying, 50.0) - 50.0) - abs(c.moneyness) * 60.0
            ),
            reverse=True,
        )

        if emit:
            audit.info(
                EventCategory.SCAN,
                f"Scanned {len(names)} underlyings",
                f"{len(chain_rows)} contracts examined → {len(approved)} cleared all gates, "
                f"{len(rejected)} rejected",
                underlyings=names,
                approved=len(approved),
                rejected=len(rejected),
                errors=errors,
            )

        return {
            "market_open": market_open,
            "profiles": [p.as_dict() for p in profiles],
            "approved": [c.as_dict() for c in approved],
            "rejected": rejected,
            "chain": chain_rows,
            "errors": errors,
            "_approved_objects": approved,
            "_profile_objects": profiles,
        }

    # ------------------------------------------------------------------ #
    # Tool 2: get_account_greeks
    # ------------------------------------------------------------------ #
    async def get_account_greeks(self) -> dict[str, Any]:
        account = await self.broker.get_account()
        view = await build_book(self.state)
        return {
            "account": account.as_dict(),
            "positions": [p.as_dict() for p in view.positions],
            "greeks": view.book.as_dict(),
            "shocked": view.shocked,
            "shocks": dict(self.state.shocks),
            "equity_at_open": self.state.equity_at_open,
        }

    # ------------------------------------------------------------------ #
    # Tool 3: execute_options_strategy
    # ------------------------------------------------------------------ #
    async def execute_options_strategy(
        self,
        symbol: str,
        side: str,
        contracts: int = 1,
        thesis: str = "",
        *,
        contract: ChainContract | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Gate-check and submit an options order.

        ``force`` skips *nothing*. It only marks the order as operator-initiated
        in the audit log; the full gate chain still runs and can still veto.
        """
        symbol = symbol.upper()
        audit = self.state.audit
        env = self.state.envelope

        from ..quant.greeks import parse_occ

        occ = parse_occ(symbol)
        if occ is None:
            audit.reject(EventCategory.GATE, "Malformed contract symbol", symbol)
            return {"submitted": False, "error": f"{symbol} is not a valid OCC option symbol."}

        # Always re-price against a live quote at submit time. The scan that
        # produced this candidate may be seconds stale, and a stale spread is
        # exactly the thing the gate exists to catch.
        if contract is None or contract.symbol != symbol:
            try:
                chain = await self.broker.get_chain(
                    occ.underlying,
                    min_dte=max(0.0, env.min_dte - 2),
                    max_dte=env.max_dte + 2,
                    moneyness_band=0.25,
                    use_cache=False,
                )
            except BrokerError as exc:
                audit.error(EventCategory.ORDER, "Quote refresh failed", str(exc), symbol=symbol)
                return {"submitted": False, "error": str(exc)}
            contract = next((c for c in chain if c.symbol == symbol), None)

        if contract is None:
            audit.reject(EventCategory.GATE, "Contract not quotable", symbol, symbol=symbol)
            return {"submitted": False, "error": f"No live quote available for {symbol}."}

        account = await self.broker.get_account()
        market_open = await self.broker.is_market_open()
        view = await build_book(self.state)

        gate: GateResult = evaluate_option_order(
            bid=contract.bid,
            ask=contract.ask,
            iv=contract.iv,
            dte=contract.dte,
            open_interest=contract.open_interest,
            contracts=contracts,
            buying_power=account.options_buying_power or account.buying_power,
            open_positions=view.book.gross_option_positions,
            day_pnl=account.day_pnl,
            equity_at_open=self.state.equity_at_open,
            market_open=market_open,
            envelope=env,
        )

        if not gate.approved:
            audit.reject(
                EventCategory.GATE,
                f"Order vetoed — {symbol}",
                gate.summary,
                symbol=symbol,
                side=side,
                contracts=contracts,
                gate=gate.as_dict(),
            )
            return {"submitted": False, "gate": gate.as_dict(), "error": gate.summary}

        audit.success(
            EventCategory.GATE,
            f"Gates cleared — {symbol}",
            gate.summary,
            symbol=symbol,
            gate=gate.as_dict(),
        )

        # Cross the full spread rather than resting at the mid. A mid-price limit
        # frequently never fills, and an agent whose orders sit unfilled all
        # session is indistinguishable from one that is broken. Crossing to the
        # far side plus one tick absorbs a quote that moves between the scan and
        # the submit, while still capping slippage at the displayed NBBO — which
        # a naked market order would not.
        assert contract.mid is not None
        from ..broker import option_tick, round_to_tick

        if side.lower() == "buy":
            raw = (contract.ask or contract.mid) + option_tick(contract.ask or contract.mid)
            limit = round_to_tick(raw, up=True)
        else:
            reference = contract.bid or contract.mid
            raw = max(option_tick(reference), reference - option_tick(reference))
            limit = round_to_tick(raw, up=False)

        try:
            order = await self.broker.submit_option_order(
                symbol=symbol,
                qty=contracts,
                side=side,
                limit_price=limit,
                client_order_id=f"magno-opt-{datetime.now(timezone.utc).timestamp():.0f}",
            )
        except BrokerError as exc:
            audit.error(EventCategory.ORDER, f"Broker rejected {symbol}", str(exc), symbol=symbol)
            return {"submitted": False, "gate": gate.as_dict(), "error": str(exc)}

        notional = (contract.mid or 0.0) * 100 * contracts
        audit.emit(
            EventCategory.ORDER,
            EventLevel.SUCCESS,
            f"{side.upper()} {contracts}x {symbol} @ ${limit:.2f} limit",
            thesis or f"Notional ${notional:,.0f} | δ {contract.greeks.delta:+.3f}/contract",
            symbol=symbol,
            side=side,
            contracts=contracts,
            limit_price=limit,
            notional=notional,
            order=order,
            greeks=contract.greeks.as_dict() if contract.greeks else None,
            forced=force,
        )
        return {"submitted": True, "order": order, "gate": gate.as_dict(), "limit_price": limit}

    # ------------------------------------------------------------------ #
    # Dry-run reasoning (demonstration harness)
    # ------------------------------------------------------------------ #
    async def dry_run_reasoning(self) -> dict[str, Any]:
        """Run scan → model → gates and stop before submitting.

        The autonomous loop refuses to spend a model call while the market is
        closed, which means the reasoner — the part most worth showing — is
        invisible outside trading hours. This runs the identical path and
        streams the thesis and full gate transcript to the ledger, then stops.

        Candidate *selection* assumes open hours so the model has something to
        reason about. The chosen order is then re-gated against reality, so
        MARKET_CLOSED still appears as the blocking verdict when it applies.
        Nothing here can submit an order.
        """
        from ..quant.risk_gate import evaluate_option_order
        from . import reasoner

        audit = self.state.audit
        env = self.state.envelope

        market_open = await self.broker.is_market_open()
        audit.info(
            EventCategory.REASONING,
            "Dry run started",
            "Scanning and reasoning without execution."
            + ("" if market_open else " Market is closed; candidate selection assumes open hours."),
            dry_run=True,
        )

        scan = await self.scan_market_volatility(assume_market_open=True)
        candidates = scan["_approved_objects"]
        profiles = scan["_profile_objects"]

        if not candidates:
            audit.warn(
                EventCategory.REASONING,
                "Dry run: no candidates",
                "Every contract failed a gate that a dry run cannot waive "
                "(spread, open interest, DTE or price band).",
                dry_run=True,
            )
            return {
                "dry_run": True,
                "market_open": market_open,
                "decision": None,
                "gate": None,
                "candidates": 0,
                "reason": "No contract cleared the non-waivable gates.",
                "profiles": [p.as_dict() for p in profiles],
            }

        account = await self.broker.get_account()
        view = await build_book(self.state)

        decision = await reasoner.reason(
            strategy=self.state.strategy,
            envelope=env,
            vol_profiles=profiles,
            candidates=candidates,
            net_delta=view.book.net_delta,
            open_positions=view.book.gross_option_positions,
            max_positions=env.max_open_positions,
            buying_power=account.options_buying_power or account.buying_power,
            day_pnl=account.day_pnl,
            max_contracts=self.state.contract_qty,
        )
        self.state.last_reasoning_at = datetime.now(timezone.utc)

        for warning in decision.warnings:
            audit.warn(EventCategory.REASONING, "Reasoner warning", warning, dry_run=True)

        if decision.diverged:
            audit.warn(
                EventCategory.REASONING,
                "Model diverged from the quant baseline",
                decision.divergence or "",
                dry_run=True,
                decision=decision.as_dict(),
            )

        origin = (
            decision.source
            + (f" · {decision.model}" if decision.model else "")
            + (f" · {decision.latency_ms}ms" if decision.latency_ms else "")
        )

        if decision.action == "HOLD" or not decision.symbol:
            audit.info(
                EventCategory.REASONING,
                "Dry run: HOLD",
                decision.thesis,
                origin=origin,
                dry_run=True,
                decision=decision.as_dict(),
            )
            return {
                "dry_run": True,
                "market_open": market_open,
                "decision": decision.as_dict(),
                "gate": None,
                "candidates": len(candidates),
                "profiles": [p.as_dict() for p in profiles],
            }

        chosen = next((c for c in candidates if c.symbol == decision.symbol), None)
        audit.info(
            EventCategory.REASONING,
            f"Dry run: would {decision.side.upper()} {decision.contracts}x {decision.symbol}",
            decision.thesis,
            origin=origin,
            confidence=decision.confidence,
            dry_run=True,
            decision=decision.as_dict(),
        )

        gate = None
        if chosen is not None:
            # Re-gate against reality. This is the honest half: it shows exactly
            # what would stop the order right now.
            gate = evaluate_option_order(
                bid=chosen.bid,
                ask=chosen.ask,
                iv=chosen.iv,
                dte=chosen.dte,
                open_interest=chosen.open_interest,
                contracts=decision.contracts,
                buying_power=account.options_buying_power or account.buying_power,
                open_positions=view.book.gross_option_positions,
                day_pnl=account.day_pnl,
                equity_at_open=self.state.equity_at_open,
                market_open=market_open,
                envelope=env,
            )
            if gate.approved:
                audit.success(
                    EventCategory.GATE,
                    f"Dry run: order would be accepted — {decision.symbol}",
                    f"{gate.summary}. Not submitted: dry run.",
                    symbol=decision.symbol,
                    gate=gate.as_dict(),
                    dry_run=True,
                )
            else:
                audit.reject(
                    EventCategory.GATE,
                    f"Dry run: order would be vetoed — {decision.symbol}",
                    gate.summary,
                    symbol=decision.symbol,
                    gate=gate.as_dict(),
                    dry_run=True,
                )

        return {
            "dry_run": True,
            "market_open": market_open,
            "decision": decision.as_dict(),
            "gate": gate.as_dict() if gate else None,
            "candidates": len(candidates),
            "contract": chosen.as_dict() if chosen else None,
            "profiles": [p.as_dict() for p in profiles],
        }

    # ------------------------------------------------------------------ #
    # Tool 4: rebalance_portfolio
    # ------------------------------------------------------------------ #
    async def rebalance_portfolio(self, force: bool = False) -> dict[str, Any]:
        """Neutralise delta drift with fractional equity orders.

        ``force`` lowers the trigger threshold to the minimum executable size so
        an operator can demand a hedge below the configured drift cap. It never
        bypasses the notional or market-hours gates.
        """
        audit = self.state.audit
        env = self.state.envelope

        account = await self.broker.get_account()
        market_open = await self.broker.is_market_open()
        view = await build_book(self.state)

        effective = env
        if force:
            from dataclasses import replace

            effective = replace(env, delta_drift_threshold=0.001)

        intents = compute_hedge_intents(
            view.book,
            effective,
            buying_power=account.buying_power,
            market_open=market_open,
        )

        if not intents:
            return {
                "hedged": False,
                "reason": (
                    f"|Δ| {abs(view.book.net_delta):.3f} is inside the "
                    f"{env.delta_drift_threshold:.2f} drift cap"
                ),
                "net_delta": view.book.net_delta,
                "intents": [],
            }

        executed: list[dict] = []
        for intent in intents:
            if intent.gate is None or not intent.gate.approved:
                reasons = intent.gate.summary if intent.gate else "no gate result"
                audit.reject(
                    EventCategory.HEDGE,
                    f"Hedge vetoed — {intent.underlying}",
                    reasons,
                    intent=intent.as_dict(),
                )
                executed.append({"intent": intent.as_dict(), "submitted": False, "error": reasons})
                continue

            audit.warn(
                EventCategory.RISK,
                f"Delta drift breach — {intent.underlying}",
                f"Net δ {intent.net_delta_before:+.3f} exceeds ±{env.delta_drift_threshold:.2f}; "
                f"neutralising with {intent.side} {intent.qty:.3f} shares",
                intent=intent.as_dict(),
            )

            if self.state.shocks:
                # A shocked book is a hypothetical. Submitting against simulated
                # prices would put a real order on the paper account for a move
                # that never happened, so the hedge is computed and logged but
                # not sent.
                audit.info(
                    EventCategory.HEDGE,
                    f"Simulated hedge — {intent.underlying}",
                    f"{intent.side} {intent.qty:.3f} shares would neutralise δ to "
                    f"{intent.projected_delta_after:+.4f}. Not submitted: shock simulation active.",
                    intent=intent.as_dict(),
                    simulated=True,
                )
                executed.append({"intent": intent.as_dict(), "submitted": False, "simulated": True})
                continue

            try:
                order = await self.broker.submit_equity_order(
                    symbol=intent.underlying,
                    qty=intent.qty,
                    side=intent.side,
                    client_order_id=f"magno-hedge-{datetime.now(timezone.utc).timestamp():.0f}",
                )
            except BrokerError as exc:
                audit.error(
                    EventCategory.HEDGE,
                    f"Hedge order failed — {intent.underlying}",
                    str(exc),
                    intent=intent.as_dict(),
                )
                executed.append({"intent": intent.as_dict(), "submitted": False, "error": str(exc)})
                continue

            audit.success(
                EventCategory.HEDGE,
                f"Hedge filled — {intent.side.upper()} {intent.qty:.3f} {intent.underlying}",
                f"δ {intent.net_delta_before:+.3f} → {intent.projected_delta_after:+.4f} "
                f"(${intent.notional:,.2f} notional)",
                intent=intent.as_dict(),
                order=order,
            )
            executed.append({"intent": intent.as_dict(), "submitted": True, "order": order})

        return {
            "hedged": any(e.get("submitted") for e in executed),
            "net_delta": view.book.net_delta,
            "intents": [i.as_dict() for i in intents],
            "executed": executed,
        }


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #
TOOL_SCHEMAS = [
    {
        "name": "scan_market_volatility",
        "description": (
            "Scan the options universe for volatility opportunities. Returns IV rank "
            "and realised-vol context per underlying plus every contract that clears "
            "Magno's liquidity, spread, open-interest, DTE and allocation gates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "underlyings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tickers to scan. Defaults to the configured universe.",
                }
            },
        },
    },
    {
        "name": "get_account_greeks",
        "description": (
            "Return the Alpaca paper account, all open positions, and aggregate "
            "portfolio Greeks (net delta, gamma, theta, vega) bucketed per underlying."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "execute_options_strategy",
        "description": (
            "Submit an options order after re-validating it against every pre-trade "
            "risk gate at a live quote. Returns the full gate transcript whether the "
            "order is approved or vetoed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "OCC option symbol, e.g. SPY250919C00450000"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "contracts": {"type": "integer", "minimum": 1, "default": 1},
                "thesis": {"type": "string", "description": "Rationale recorded in the audit log."},
            },
            "required": ["symbol", "side"],
        },
    },
    {
        "name": "rebalance_portfolio",
        "description": (
            "Neutralise portfolio delta drift by submitting fractional equity orders "
            "per underlying. No-ops when |net delta| is inside the configured drift cap."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Hedge any non-zero delta rather than waiting for the drift cap.",
                }
            },
        },
    },
]


async def _headless_session() -> SessionState:
    """Build a session from environment credentials for standalone MCP use."""
    from ..events import AuditLog
    from ..quant.risk_gate import RiskEnvelope
    from ..state_store import SessionState, Strategy

    if not settings.alpaca_api_key or not settings.alpaca_secret_key:
        raise BrokerError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set to run the MCP server standalone."
        )
    broker = AlpacaBroker(settings.alpaca_api_key, settings.alpaca_secret_key)
    account = await broker.get_account()
    return SessionState(
        session_id="mcp-stdio",
        broker=broker,
        envelope=RiskEnvelope(
            max_spread_pct=settings.max_spread_pct,
            max_allocation_pct=settings.max_allocation_pct,
            delta_drift_threshold=settings.delta_drift_threshold,
            max_daily_loss_pct=settings.max_daily_loss_pct,
            max_open_positions=settings.max_open_positions,
        ),
        strategy=Strategy.ADAPTIVE_VRP,
        audit=AuditLog(),
        account=account,
        created_at=datetime.now(timezone.utc),
        equity_at_open=account.last_equity or account.equity,
        contract_qty=settings.default_contract_qty,
    )


def build_mcp_server():
    """Construct the stdio MCP server exposing Magno's four tools."""
    import json

    import mcp.types as types
    from mcp.server import Server

    server = Server("magno-alpaca")
    session_holder: dict[str, SessionState] = {}

    async def get_session() -> SessionState:
        if "state" not in session_holder:
            session_holder["state"] = await _headless_session()
        return session_holder["state"]

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(**schema) for schema in TOOL_SCHEMAS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
        args = arguments or {}
        try:
            tools = MagnoTools(await get_session())
            if name == "scan_market_volatility":
                result = await tools.scan_market_volatility(args.get("underlyings"))
                # Strip the internal object handles; MCP payloads must be JSON.
                result = {k: v for k, v in result.items() if not k.startswith("_")}
            elif name == "get_account_greeks":
                result = await tools.get_account_greeks()
            elif name == "execute_options_strategy":
                result = await tools.execute_options_strategy(
                    symbol=args["symbol"],
                    side=args["side"],
                    contracts=int(args.get("contracts", 1)),
                    thesis=args.get("thesis", ""),
                )
            elif name == "rebalance_portfolio":
                result = await tools.rebalance_portfolio(force=bool(args.get("force", False)))
            else:
                raise ValueError(f"Unknown tool: {name}")
        except Exception as exc:
            log.exception("MCP tool %s failed", name)
            result = {"error": f"{type(exc).__name__}: {exc}"}
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    return server


async def _run_stdio() -> None:
    import mcp.server.stdio

    server = build_mcp_server()
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_stdio())
