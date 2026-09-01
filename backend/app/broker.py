"""Typed async adapter over the Alpaca paper-trading and market-data APIs.

alpaca-py is synchronous, so every call is dispatched to a worker thread with
``asyncio.to_thread`` to keep the FastAPI event loop (and the 1 Hz telemetry
tick) responsive.

Three deliberate choices:

* **Paper only.** ``TradingClient`` is always constructed with ``paper=True``.
  There is no code path in Magno that can reach a live endpoint.
* **Greeks are computed locally.** Alpaca returns Greeks only on OPRA-subscribed
  accounts and they are routinely ``None`` on paper, so we invert implied vol
  from the NBBO mid and derive our own -- preferring Alpaca's values whenever
  they are actually present.
* **Open interest comes from the contracts endpoint.** Option snapshots carry
  quotes but not OI, so the chain is assembled by joining
  ``get_option_contracts`` (OI, strike, expiry, tradability) onto
  ``get_option_chain`` (NBBO, IV, Greeks).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import (
    AssetStatus,
    ContractType,
    OrderClass,
    OrderSide,
    OrderStatus,
    PositionIntent,
    QueryOrderStatus,
    TimeInForce,
)
from alpaca.trading.requests import (
    GetOptionContractsRequest,
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    OptionLegRequest,
)

from .config import settings
from .quant.greeks import (
    Greeks,
    bs_greeks,
    implied_volatility,
    parse_occ,
    percentile_rank,
    realized_volatility,
    rolling_realized_vol_series,
)
from .quant.hedge_engine import PositionSnapshot
from .quant.risk_gate import mid_price, spread_pct

log = logging.getLogger("magno.broker")

SPOT_TTL_S = 3.0
VOL_TTL_S = 900.0
CHAIN_TTL_S = 20.0


class BrokerError(RuntimeError):
    """Raised for credential and upstream failures with an operator-readable message."""


@dataclass
class AccountSnapshot:
    account_id: str
    account_number: str
    status: str
    equity: float
    last_equity: float
    cash: float
    buying_power: float
    options_buying_power: float
    portfolio_value: float
    long_market_value: float
    short_market_value: float
    options_trading_level: int
    pattern_day_trader: bool
    trading_blocked: bool
    currency: str = "USD"

    @property
    def day_pnl(self) -> float:
        return self.equity - self.last_equity

    @property
    def day_pnl_pct(self) -> float:
        return (self.day_pnl / self.last_equity) if self.last_equity else 0.0

    def as_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "account_number": self.account_number,
            "status": self.status,
            "equity": self.equity,
            "last_equity": self.last_equity,
            "cash": self.cash,
            "buying_power": self.buying_power,
            "options_buying_power": self.options_buying_power,
            "portfolio_value": self.portfolio_value,
            "long_market_value": self.long_market_value,
            "short_market_value": self.short_market_value,
            "options_trading_level": self.options_trading_level,
            "pattern_day_trader": self.pattern_day_trader,
            "trading_blocked": self.trading_blocked,
            "currency": self.currency,
            "day_pnl": self.day_pnl,
            "day_pnl_pct": self.day_pnl_pct,
        }


@dataclass
class ChainContract:
    """One option contract, fully enriched and pre-scored for the risk gates."""

    symbol: str
    underlying: str
    right: str
    strike: float
    expiry: str
    dte: float
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    spread_pct: float | None
    open_interest: int | None
    iv: float | None
    iv_source: str
    greeks: Greeks | None
    greeks_source: str
    spot: float
    tradable: bool
    moneyness: float

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "right": self.right,
            "strike": self.strike,
            "expiry": self.expiry,
            "dte": self.dte,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "last": self.last,
            "spread_pct": self.spread_pct,
            "open_interest": self.open_interest,
            "iv": self.iv,
            "iv_source": self.iv_source,
            "greeks": self.greeks.as_dict() if self.greeks else None,
            "greeks_source": self.greeks_source,
            "spot": self.spot,
            "tradable": self.tradable,
            "moneyness": self.moneyness,
        }


@dataclass
class VolProfile:
    """Volatility context for one underlying, used to rank opportunities.

    Alpaca does not publish a historical implied-vol surface, so ``iv_rank`` is
    the percentile of the current ATM implied vol measured against the trailing
    one-year distribution of 20-day realised volatility. It is explicitly a
    proxy and is labelled as such in the UI -- but it is a *real* percentile
    computed from real bars, not a placeholder.
    """

    underlying: str
    spot: float
    atm_iv: float | None
    realized_vol_20d: float | None
    iv_rank: float | None
    iv_premium: float | None  # ATM IV minus 20d realised: positive = vol is rich
    sample_size: int

    def as_dict(self) -> dict:
        return {
            "underlying": self.underlying,
            "spot": self.spot,
            "atm_iv": self.atm_iv,
            "realized_vol_20d": self.realized_vol_20d,
            "iv_rank": self.iv_rank,
            "iv_premium": self.iv_premium,
            "sample_size": self.sample_size,
        }


@dataclass
class _Cache:
    spots: dict[str, tuple[float, float]] = field(default_factory=dict)
    vol_series: dict[str, tuple[float, list[float], float | None]] = field(default_factory=dict)
    chains: dict[str, tuple[float, list[ChainContract]]] = field(default_factory=dict)


class AlpacaBroker:
    """All Alpaca I/O for a single operator session."""

    def __init__(self, api_key: str, secret_key: str) -> None:
        if not api_key or not secret_key:
            raise BrokerError("Alpaca API key and secret are both required.")
        self.api_key = api_key
        self.secret_key = secret_key
        # paper=True is not configurable. Magno cannot trade live capital.
        self.trading = TradingClient(api_key, secret_key, paper=True)
        self.stock_data = StockHistoricalDataClient(api_key, secret_key)
        self.option_data = OptionHistoricalDataClient(api_key, secret_key)
        self._cache = _Cache()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Account
    # ------------------------------------------------------------------ #
    async def get_account(self) -> AccountSnapshot:
        try:
            acct = await asyncio.to_thread(self.trading.get_account)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc

        def f(value: Any, default: float = 0.0) -> float:
            try:
                return float(value) if value is not None else default
            except (TypeError, ValueError):
                return default

        return AccountSnapshot(
            account_id=str(acct.id),
            account_number=str(acct.account_number),
            status=str(getattr(acct.status, "value", acct.status)),
            equity=f(acct.equity),
            last_equity=f(acct.last_equity),
            cash=f(acct.cash),
            buying_power=f(acct.buying_power),
            options_buying_power=f(getattr(acct, "options_buying_power", None)),
            portfolio_value=f(acct.portfolio_value),
            long_market_value=f(acct.long_market_value),
            short_market_value=f(acct.short_market_value),
            options_trading_level=int(getattr(acct, "options_trading_level", 0) or 0),
            pattern_day_trader=bool(acct.pattern_day_trader),
            trading_blocked=bool(acct.trading_blocked),
            currency=str(acct.currency or "USD"),
        )

    async def is_market_open(self) -> bool:
        try:
            clock = await asyncio.to_thread(self.trading.get_clock)
            return bool(clock.is_open)
        except APIError:
            return False

    async def get_clock(self) -> dict:
        try:
            clock = await asyncio.to_thread(self.trading.get_clock)
            return {
                "is_open": bool(clock.is_open),
                "timestamp": clock.timestamp.isoformat(),
                "next_open": clock.next_open.isoformat(),
                "next_close": clock.next_close.isoformat(),
            }
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #
    async def get_spot(self, symbol: str) -> float | None:
        spots = await self.get_spots([symbol])
        return spots.get(symbol)

    async def get_spots(self, symbols: list[str]) -> dict[str, float]:
        """Latest trade price per symbol, cached for a few seconds."""
        symbols = [s.upper() for s in symbols]
        now = time.monotonic()
        out: dict[str, float] = {}
        stale = []
        for sym in symbols:
            hit = self._cache.spots.get(sym)
            if hit and now - hit[0] < SPOT_TTL_S:
                out[sym] = hit[1]
            else:
                stale.append(sym)
        if not stale:
            return out

        try:
            req = StockLatestTradeRequest(symbol_or_symbols=stale, feed=DataFeed.IEX)
            trades = await asyncio.to_thread(self.stock_data.get_stock_latest_trade, req)
            for sym, trade in trades.items():
                price = float(trade.price)
                if price > 0:
                    out[sym] = price
                    self._cache.spots[sym] = (now, price)
        except APIError as exc:
            log.warning("spot fetch failed for %s: %s", stale, exc)
        return out

    async def get_daily_closes(self, symbol: str, lookback_days: int = 400) -> list[float]:
        symbol = symbol.upper()
        end = datetime.now(timezone.utc) - timedelta(minutes=20)  # respect IEX delay
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=end - timedelta(days=lookback_days),
            end=end,
            feed=DataFeed.IEX,
        )
        try:
            bars = await asyncio.to_thread(self.stock_data.get_stock_bars, req)
        except APIError as exc:
            log.warning("bars fetch failed for %s: %s", symbol, exc)
            return []
        rows = bars.data.get(symbol, []) if hasattr(bars, "data") else []
        return [float(b.close) for b in rows if b.close]

    async def get_vol_profile(self, underlying: str, atm_iv: float | None = None) -> VolProfile:
        """Realised-vol distribution plus the IV-rank proxy for one underlying."""
        underlying = underlying.upper()
        now = time.monotonic()
        cached = self._cache.vol_series.get(underlying)
        if cached and now - cached[0] < VOL_TTL_S:
            _, series, rv20 = cached
        else:
            closes = await self.get_daily_closes(underlying)
            series = rolling_realized_vol_series(closes, window=20)
            rv20 = realized_volatility(closes, window=20)
            self._cache.vol_series[underlying] = (now, series, rv20)

        spot = (await self.get_spots([underlying])).get(underlying, 0.0)
        iv_rank = percentile_rank(atm_iv, series) if atm_iv is not None else None
        premium = (atm_iv - rv20) if (atm_iv is not None and rv20 is not None) else None
        return VolProfile(
            underlying=underlying,
            spot=spot,
            atm_iv=atm_iv,
            realized_vol_20d=rv20,
            iv_rank=iv_rank,
            iv_premium=premium,
            sample_size=len(series),
        )

    # ------------------------------------------------------------------ #
    # Option chain
    # ------------------------------------------------------------------ #
    async def get_chain(
        self,
        underlying: str,
        *,
        min_dte: float = 5.0,
        max_dte: float = 60.0,
        moneyness_band: float = 0.12,
        right: str | None = None,
        use_cache: bool = True,
    ) -> list[ChainContract]:
        underlying = underlying.upper()
        cache_key = f"{underlying}:{min_dte}:{max_dte}:{moneyness_band}:{right}"
        now = time.monotonic()
        if use_cache:
            hit = self._cache.chains.get(cache_key)
            if hit and now - hit[0] < CHAIN_TTL_S:
                return hit[1]

        spot = (await self.get_spots([underlying])).get(underlying)
        if not spot:
            raise BrokerError(f"No spot price available for {underlying}.")

        today = date.today()
        exp_gte = today + timedelta(days=int(min_dte))
        exp_lte = today + timedelta(days=int(max_dte))
        strike_lo = round(spot * (1 - moneyness_band), 2)
        strike_hi = round(spot * (1 + moneyness_band), 2)
        contract_type = (
            ContractType.CALL if right == "C" else ContractType.PUT if right == "P" else None
        )

        contracts, snapshots = await asyncio.gather(
            self._fetch_contracts(underlying, exp_gte, exp_lte, strike_lo, strike_hi, contract_type),
            self._fetch_snapshots(underlying, exp_gte, exp_lte, strike_lo, strike_hi, contract_type),
            return_exceptions=True,
        )
        if isinstance(snapshots, BaseException):
            raise BrokerError(f"Option chain unavailable for {underlying}: {snapshots}")
        if isinstance(contracts, BaseException):
            log.warning("contract metadata unavailable for %s: %s", underlying, contracts)
            contracts = {}

        rows: list[ChainContract] = []
        for symbol, snap in snapshots.items():
            occ = parse_occ(symbol)
            if occ is None:
                continue
            meta = contracts.get(symbol)
            row = self._build_contract(occ, snap, meta, spot)
            if row is not None:
                rows.append(row)

        rows.sort(key=lambda r: (r.expiry, r.right, r.strike))
        self._cache.chains[cache_key] = (now, rows)
        return rows

    async def _fetch_contracts(
        self,
        underlying: str,
        exp_gte: date,
        exp_lte: date,
        strike_lo: float,
        strike_hi: float,
        contract_type: ContractType | None,
    ) -> dict[str, Any]:
        req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            status=AssetStatus.ACTIVE,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            strike_price_gte=str(strike_lo),
            strike_price_lte=str(strike_hi),
            type=contract_type,
            limit=10_000,
        )
        resp = await asyncio.to_thread(self.trading.get_option_contracts, req)
        items = getattr(resp, "option_contracts", None) or []
        return {c.symbol: c for c in items}

    async def _fetch_snapshots(
        self,
        underlying: str,
        exp_gte: date,
        exp_lte: date,
        strike_lo: float,
        strike_hi: float,
        contract_type: ContractType | None,
    ) -> dict[str, Any]:
        req = OptionChainRequest(
            underlying_symbol=underlying,
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            strike_price_gte=strike_lo,
            strike_price_lte=strike_hi,
            type=contract_type,
            # Paper keys are not OPRA-entitled; the indicative feed is the one
            # that actually returns quotes for them.
            feed=OptionsFeed.INDICATIVE,
        )
        try:
            return await asyncio.to_thread(self.option_data.get_option_chain, req)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc

    def _build_contract(self, occ, snap, meta, spot: float) -> ChainContract | None:
        quote = getattr(snap, "latest_quote", None)
        trade = getattr(snap, "latest_trade", None)
        bid = float(quote.bid_price) if quote and quote.bid_price else None
        ask = float(quote.ask_price) if quote and quote.ask_price else None
        last = float(trade.price) if trade and trade.price else None
        mid = mid_price(bid, ask)
        # Fall back to the last print when the book is one-sided, so the row can
        # still be displayed and scored -- the spread gate will reject it anyway.
        ref_price = mid if mid is not None else last

        t = occ.year_fraction()
        iv = getattr(snap, "implied_volatility", None)
        iv = float(iv) if iv else None
        iv_source = "alpaca"
        if iv is None and ref_price:
            iv = implied_volatility(ref_price, spot, occ.strike, t, settings.risk_free_rate, occ.is_call)
            iv_source = "magno_bsm" if iv is not None else "unavailable"

        greeks: Greeks | None = None
        greeks_source = "unavailable"
        raw = getattr(snap, "greeks", None)
        if raw is not None and getattr(raw, "delta", None) is not None:
            greeks = Greeks(
                delta=float(raw.delta),
                gamma=float(raw.gamma or 0.0),
                theta=float(raw.theta or 0.0) / 365.0,
                vega=float(raw.vega or 0.0) / 100.0,
                rho=float(getattr(raw, "rho", 0.0) or 0.0) / 100.0,
                iv=iv or 0.0,
                price=ref_price or 0.0,
            )
            greeks_source = "alpaca"
        elif iv is not None:
            greeks = bs_greeks(spot, occ.strike, t, settings.risk_free_rate, iv, occ.is_call)
            greeks_source = "magno_bsm"

        oi = int(meta.open_interest) if meta and meta.open_interest else None
        tradable = bool(meta.tradable) if meta is not None else True

        return ChainContract(
            symbol=occ.symbol,
            underlying=occ.underlying,
            right=occ.right,
            strike=occ.strike,
            expiry=occ.expiry.isoformat(),
            dte=occ.days_to_expiry(),
            bid=bid,
            ask=ask,
            mid=mid,
            last=last,
            spread_pct=spread_pct(bid, ask),
            open_interest=oi,
            iv=iv,
            iv_source=iv_source,
            greeks=greeks,
            greeks_source=greeks_source,
            spot=spot,
            tradable=tradable,
            moneyness=(occ.strike / spot - 1.0) if spot else 0.0,
        )

    async def atm_iv(self, underlying: str) -> float | None:
        """Implied vol of the nearest-the-money contract, for the vol profile."""
        try:
            chain = await self.get_chain(underlying, min_dte=14, max_dte=45, moneyness_band=0.05)
        except BrokerError:
            return None
        candidates = [c for c in chain if c.iv is not None]
        if not candidates:
            return None
        nearest = min(candidates, key=lambda c: abs(c.moneyness))
        near_atm = [c.iv for c in candidates if abs(c.moneyness) <= abs(nearest.moneyness) + 0.005]
        return sum(near_atm) / len(near_atm)

    # ------------------------------------------------------------------ #
    # Positions
    # ------------------------------------------------------------------ #
    async def get_positions(self) -> list[PositionSnapshot]:
        try:
            raw = await asyncio.to_thread(self.trading.get_all_positions)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc

        underlyings = set()
        parsed: list[tuple[Any, Any]] = []
        for p in raw:
            occ = parse_occ(p.symbol)
            parsed.append((p, occ))
            underlyings.add(occ.underlying if occ else p.symbol.upper())

        spots = await self.get_spots(sorted(underlyings))
        out: list[PositionSnapshot] = []
        for p, occ in parsed:
            qty = float(p.qty)
            current = float(p.current_price or 0.0)
            snapshot = PositionSnapshot(
                symbol=p.symbol,
                underlying=occ.underlying if occ else p.symbol.upper(),
                asset_class="us_option" if occ else "us_equity",
                qty=qty,
                market_value=float(p.market_value or 0.0),
                unrealized_pl=float(p.unrealized_pl or 0.0),
                avg_entry_price=float(p.avg_entry_price or 0.0),
                current_price=current,
                strike=occ.strike if occ else None,
                expiry=occ.expiry.isoformat() if occ else None,
                right=occ.right if occ else None,
                dte=occ.days_to_expiry() if occ else None,
            )
            if occ:
                spot = spots.get(occ.underlying)
                if spot:
                    t = occ.year_fraction()
                    iv = implied_volatility(
                        current, spot, occ.strike, t, settings.risk_free_rate, occ.is_call
                    )
                    # A stale or one-sided mark can be un-invertible; a 30% vol
                    # placeholder keeps the position delta-managed rather than
                    # silently dropping it out of the hedge calculation.
                    snapshot.greeks = bs_greeks(
                        spot, occ.strike, t, settings.risk_free_rate, iv if iv else 0.30, occ.is_call
                    )
            out.append(snapshot)
        return out

    # ------------------------------------------------------------------ #
    # Orders
    # ------------------------------------------------------------------ #
    async def submit_equity_order(
        self, symbol: str, qty: float, side: str, client_order_id: str | None = None
    ) -> dict:
        request = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=round(abs(qty), 3),
            side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
            # Fractional quantities are only accepted as market DAY orders.
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        return await self._submit(request)

    async def submit_option_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        limit_price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        if limit_price is not None:
            request = LimitOrderRequest(
                symbol=symbol.upper(),
                qty=int(abs(qty)),
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=round(limit_price, 2),
                client_order_id=client_order_id,
            )
        else:
            request = MarketOrderRequest(
                symbol=symbol.upper(),
                qty=int(abs(qty)),
                side=order_side,
                time_in_force=TimeInForce.DAY,
                client_order_id=client_order_id,
            )
        return await self._submit(request)

    async def submit_vertical_spread(
        self,
        short_symbol: str,
        long_symbol: str,
        qty: int,
        limit_credit: float,
        client_order_id: str | None = None,
    ) -> dict:
        """Submit both legs of a credit vertical as one atomic package.

        Legging in separately is the failure mode this exists to avoid: if the
        short fills and the long does not, the account is holding naked risk —
        precisely the thing the spread was built to prevent. Alpaca's MLEG order
        class fills both legs or neither.

        ``limit_credit`` is the net credit per share. Alpaca expresses a
        multi-leg credit as a negative limit price.
        """
        request = LimitOrderRequest(
            qty=int(abs(qty)),
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            limit_price=round(abs(limit_credit), 2) * -1,
            client_order_id=client_order_id,
            legs=[
                OptionLegRequest(
                    symbol=short_symbol.upper(),
                    ratio_qty=1,
                    side=OrderSide.SELL,
                    position_intent=PositionIntent.SELL_TO_OPEN,
                ),
                OptionLegRequest(
                    symbol=long_symbol.upper(),
                    ratio_qty=1,
                    side=OrderSide.BUY,
                    position_intent=PositionIntent.BUY_TO_OPEN,
                ),
            ],
        )
        return await self._submit(request)

    async def _submit(self, request) -> dict:
        try:
            order = await asyncio.to_thread(self.trading.submit_order, request)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc
        return _order_dict(order)

    async def get_recent_orders(self, limit: int = 50) -> list[dict]:
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit, direction="desc")
        try:
            orders = await asyncio.to_thread(self.trading.get_orders, req)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc
        return [_order_dict(o) for o in orders]

    async def get_open_orders(self) -> list[dict]:
        """Orders that are live at the broker but not yet resolved."""
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=200, direction="desc")
        try:
            orders = await asyncio.to_thread(self.trading.get_orders, req)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc
        return [_order_dict(o) for o in orders]

    async def in_flight_equity_delta(self) -> dict[str, float]:
        """Share-equivalent delta already committed but not yet filled, per symbol.

        This closes a live runaway. The hedge engine derives net delta from
        *positions*, and a position does not change until a fill settles. When
        an order rests unfilled -- a name that has not crossed in the opening
        auction, a limit the market moved away from -- the engine kept seeing
        the same uncorrected exposure and fired another identical hedge every
        cycle. Observed in production: nine stacked 56-share shorts against a
        position that needed one, which would have left the account short
        roughly 500 shares had they all filled at once.

        A resting sell of 57 shares is -57 delta that is *already committed*.
        Counting it prevents ordering it twice.
        """
        out: dict[str, float] = {}
        for order in await self.get_open_orders():
            if order.get("asset_class") != "us_equity":
                continue
            # Only the unfilled remainder is still in flight.
            remaining = float(order.get("qty") or 0.0) - float(order.get("filled_qty") or 0.0)
            if remaining <= 0:
                continue
            signed = remaining if str(order.get("side", "")).lower() == "buy" else -remaining
            symbol = str(order.get("symbol", "")).upper()
            out[symbol] = out.get(symbol, 0.0) + signed
        return out

    async def cancel_order(self, order_id: str) -> None:
        """Cancel a resting order.

        Needed for any order that does not fill immediately — an options order
        placed outside trading hours, or a limit that the market moves away
        from. Without it the only way to clear a stuck order is the Alpaca
        dashboard, which is not an acceptable answer for an autonomous agent.
        """
        try:
            await asyncio.to_thread(self.trading.cancel_order_by_id, order_id)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc

    async def cancel_all_orders(self) -> int:
        """Cancel every open order. The panic button."""
        try:
            responses = await asyncio.to_thread(self.trading.cancel_orders)
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc
        return len(responses or [])

    async def close_position(self, symbol: str) -> dict:
        try:
            order = await asyncio.to_thread(self.trading.close_position, symbol.upper())
        except APIError as exc:
            raise BrokerError(_friendly_api_error(exc)) from exc
        return _order_dict(order)


def _order_dict(order) -> dict:
    def val(x):
        return getattr(x, "value", x)

    filled_qty = float(order.filled_qty or 0)
    return {
        "id": str(order.id),
        "client_order_id": order.client_order_id,
        "symbol": order.symbol,
        "asset_class": str(val(order.asset_class)) if order.asset_class else None,
        "side": str(val(order.side)),
        "type": str(val(order.type)),
        "qty": float(order.qty) if order.qty else filled_qty,
        "filled_qty": filled_qty,
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "limit_price": float(order.limit_price) if order.limit_price else None,
        "status": str(val(order.status)),
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
    }


def option_tick(price: float) -> float:
    """OPRA minimum price increment.

    Contracts under $3.00 quote in $0.01; at or above $3.00 they quote in $0.05.
    A limit that lands off this grid is rejected by the exchange, so a naive
    ``round(price, 2)`` breaks on any contract priced above $3 — which is most
    of a liquid SPY chain.
    """
    return 0.01 if price < 3.0 else 0.05


def round_to_tick(price: float, *, up: bool) -> float:
    """Snap a limit onto the OPRA grid, rounding in the direction that keeps the
    order marketable (up for buys, down for sells)."""
    tick = option_tick(price)
    steps = price / tick
    snapped = (math.ceil(steps) if up else math.floor(steps)) * tick
    return round(max(snapped, tick), 2)


TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
}


def _friendly_api_error(exc: APIError) -> str:
    """Turn Alpaca's raw error bodies into something an operator can act on.

    The cardinal rule here is that context is *added* to Alpaca's own words, never
    substituted for them. An earlier version collapsed 401 and 403 into a single
    "bad credentials" message, which meant a perfectly valid rejection — Alpaca
    refusing a fractional short sale — was reported as an authentication failure
    on keys that were demonstrably working. That sends an operator hunting for a
    problem that does not exist, during a live run, which is the worst possible
    moment. The two codes mean different things:

        401  the keys are wrong
        403  the keys are fine; the *action* is not permitted

    So 403 keeps Alpaca's payload verbatim and only prepends a hint.
    """
    text = str(exc)
    lowered = text.lower()
    code = getattr(exc, "status_code", None)

    if code == 401:
        return (
            "Alpaca rejected these credentials (401). Confirm you are using "
            "**paper** keys from the Paper Trading dashboard, not live keys."
        )

    if code == 403:
        # Forbidden action, not a bad key. Lead with the specific cause when we
        # recognise it, but always carry Alpaca's own text through.
        if "fractional" in lowered and ("short" in lowered or "sell" in lowered):
            hint = (
                "Alpaca does not permit fractional short sales. A short hedge must "
                "be a whole number of shares"
            )
        elif "options" in lowered and "level" in lowered:
            hint = (
                "This paper account is not approved for the requested options level. "
                "Raise it in the Alpaca paper dashboard"
            )
        elif "buying power" in lowered or "insufficient" in lowered:
            hint = "Insufficient buying power for this order"
        else:
            hint = "Alpaca refused this action (403); the credentials are valid"
        return f"{hint} — Alpaca said: {text}"

    if code == 429:
        return f"Alpaca rate limit hit (429). Magno will retry on the next cycle. ({text})"

    if "subscription" in lowered or "not authorized" in lowered:
        return f"Alpaca data entitlement issue: {text}"

    if code == 422:
        return f"Alpaca rejected the order as malformed (422): {text}"

    return text
