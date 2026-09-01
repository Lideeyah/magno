"""Black-Scholes-Merton pricing, implied volatility inversion and Greeks.

Alpaca's option snapshots expose broker-computed Greeks only on OPRA-subscribed
accounts, and they are frequently ``None`` on paper. Magno therefore computes
its own Greeks from the NBBO mid price so the hedging loop never depends on an
optional upstream field. When Alpaca *does* supply Greeks we prefer them and
fall back to ours -- see ``app.market.build_contract``.

All functions are pure and side-effect free so they can be unit tested without
network access (``python -m app.quant.selftest``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

SQRT_2PI = math.sqrt(2.0 * math.pi)
DAYS_PER_YEAR = 365.0
# Below this time-to-expiry or vol the BSM formula degenerates; we clamp instead
# of dividing by zero so an expiring contract still yields a usable delta.
MIN_T = 1.0 / (DAYS_PER_YEAR * 24.0)  # one hour
MIN_SIGMA = 1e-4
MAX_SIGMA = 5.0

OCC_RE = re.compile(r"^(?P<root>[A-Z]{1,6})(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class Greeks:
    """Per-contract Greeks, expressed per 1 contract (100 shares) where noted."""

    delta: float          # per share, in [-1, 1]
    gamma: float          # per share, per $1 move
    theta: float          # per share, per calendar day (negative for long premium)
    vega: float           # per share, per 1 vol point (0.01)
    rho: float            # per share, per 1 rate point (0.01)
    iv: float             # annualised implied volatility, decimal
    price: float          # theoretical price per share

    def as_dict(self) -> dict[str, float]:
        return {
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
            "iv": self.iv,
            "price": self.price,
        }


# --------------------------------------------------------------------------- #
# Normal distribution helpers
# --------------------------------------------------------------------------- #
def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    # math.erf is accurate to ~1e-16 and avoids a scipy import on the hot path.
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# --------------------------------------------------------------------------- #
# Core BSM
# --------------------------------------------------------------------------- #
def _d1_d2(s: float, k: float, t: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    vol_t = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / vol_t
    return d1, d1 - vol_t


def bs_price(
    s: float, k: float, t: float, r: float, sigma: float, is_call: bool, q: float = 0.0
) -> float:
    """European option price under Black-Scholes-Merton with continuous yield ``q``."""
    t = max(t, MIN_T)
    sigma = max(sigma, MIN_SIGMA)
    if s <= 0 or k <= 0:
        return 0.0
    d1, d2 = _d1_d2(s, k, t, r, q, sigma)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    if is_call:
        return s * disc_q * norm_cdf(d1) - k * disc_r * norm_cdf(d2)
    return k * disc_r * norm_cdf(-d2) - s * disc_q * norm_cdf(-d1)


def bs_greeks(
    s: float, k: float, t: float, r: float, sigma: float, is_call: bool, q: float = 0.0
) -> Greeks:
    """Analytic first- and second-order Greeks. Theta is per *calendar day*."""
    t = max(t, MIN_T)
    sigma = max(min(sigma, MAX_SIGMA), MIN_SIGMA)
    d1, d2 = _d1_d2(s, k, t, r, q, sigma)
    sqrt_t = math.sqrt(t)
    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    pdf_d1 = norm_pdf(d1)

    gamma = disc_q * pdf_d1 / (s * sigma * sqrt_t)
    vega = s * disc_q * pdf_d1 * sqrt_t / 100.0  # per 1 vol point

    common_theta = -(s * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
    if is_call:
        delta = disc_q * norm_cdf(d1)
        theta = common_theta - r * k * disc_r * norm_cdf(d2) + q * s * disc_q * norm_cdf(d1)
        rho = k * t * disc_r * norm_cdf(d2) / 100.0
    else:
        delta = -disc_q * norm_cdf(-d1)
        theta = common_theta + r * k * disc_r * norm_cdf(-d2) - q * s * disc_q * norm_cdf(-d1)
        rho = -k * t * disc_r * norm_cdf(-d2) / 100.0

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta / DAYS_PER_YEAR,
        vega=vega,
        rho=rho,
        iv=sigma,
        price=bs_price(s, k, t, r, sigma, is_call, q),
    )


# --------------------------------------------------------------------------- #
# Implied volatility
# --------------------------------------------------------------------------- #
def implied_volatility(
    market_price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    is_call: bool,
    q: float = 0.0,
) -> float | None:
    """Invert BSM for sigma.

    Newton-Raphson seeded with the Brenner-Subrahmanyam ATM approximation, with a
    bisection fallback for the wings where vega collapses and Newton stalls.
    Returns ``None`` when the quote violates arbitrage bounds (which is itself a
    useful signal -- ``risk_gate`` treats an un-invertible quote as untradeable).
    """
    t = max(t, MIN_T)
    if market_price <= 0 or s <= 0 or k <= 0:
        return None

    disc_r, disc_q = math.exp(-r * t), math.exp(-q * t)
    intrinsic = max(s * disc_q - k * disc_r, 0.0) if is_call else max(k * disc_r - s * disc_q, 0.0)
    upper_bound = s * disc_q if is_call else k * disc_r
    # A quote below intrinsic or above the payoff cap cannot be inverted.
    if market_price < intrinsic - 1e-8 or market_price > upper_bound + 1e-8:
        return None

    sigma = max(math.sqrt(2.0 * math.pi / t) * market_price / s, 0.05)
    sigma = min(max(sigma, MIN_SIGMA), MAX_SIGMA)

    for _ in range(60):
        price = bs_price(s, k, t, r, sigma, is_call, q)
        diff = price - market_price
        if abs(diff) < 1e-8:
            return sigma
        d1, _ = _d1_d2(s, k, t, r, q, sigma)
        vega = s * disc_q * norm_pdf(d1) * math.sqrt(t)
        if vega < 1e-10:
            break
        step = diff / vega
        # Damp the step so a bad seed cannot fling sigma out of the bracket.
        sigma_next = sigma - max(min(step, 1.0), -1.0)
        if sigma_next <= MIN_SIGMA or sigma_next >= MAX_SIGMA or math.isnan(sigma_next):
            break
        if abs(sigma_next - sigma) < 1e-10:
            return sigma_next
        sigma = sigma_next

    lo, hi = MIN_SIGMA, MAX_SIGMA
    if bs_price(s, k, t, r, hi, is_call, q) < market_price:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs_price(s, k, t, r, mid, is_call, q) < market_price:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9:
            break
    result = 0.5 * (lo + hi)
    return result if MIN_SIGMA < result < MAX_SIGMA - 1e-6 else None


# --------------------------------------------------------------------------- #
# OCC symbology
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OccSymbol:
    symbol: str
    underlying: str
    expiry: date
    is_call: bool
    strike: float

    @property
    def right(self) -> str:
        return "C" if self.is_call else "P"

    def year_fraction(self, now: datetime | None = None) -> float:
        """Calendar-day time to expiry, expiry treated as 16:00 ET (20:00 UTC)."""
        now = now or datetime.now(timezone.utc)
        expiry_dt = datetime(
            self.expiry.year, self.expiry.month, self.expiry.day, 20, 0, tzinfo=timezone.utc
        )
        return max((expiry_dt - now).total_seconds() / (DAYS_PER_YEAR * 86400.0), MIN_T)

    def days_to_expiry(self, now: datetime | None = None) -> float:
        return self.year_fraction(now) * DAYS_PER_YEAR


def parse_occ(symbol: str) -> OccSymbol | None:
    """Parse an OCC-21 option symbol, e.g. ``SPY250919C00450000``."""
    m = OCC_RE.match(symbol.strip().upper())
    if not m:
        return None
    try:
        expiry = date(2000 + int(m["yy"]), int(m["mm"]), int(m["dd"]))
    except ValueError:
        return None
    return OccSymbol(
        symbol=symbol.strip().upper(),
        underlying=m["root"],
        expiry=expiry,
        is_call=m["cp"] == "C",
        strike=int(m["strike"]) / 1000.0,
    )


# --------------------------------------------------------------------------- #
# Realised volatility (used for the IV-rank proxy)
# --------------------------------------------------------------------------- #
def realized_volatility(closes: list[float], window: int = 20) -> float | None:
    """Annualised close-to-close realised volatility over the trailing window."""
    if len(closes) < window + 1:
        return None
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252.0)


def rolling_realized_vol_series(closes: list[float], window: int = 20) -> list[float]:
    out: list[float] = []
    for end in range(window + 1, len(closes) + 1):
        rv = realized_volatility(closes[:end], window)
        if rv is not None:
            out.append(rv)
    return out


def percentile_rank(value: float, series: list[float]) -> float | None:
    """Fraction of the series at or below ``value``, scaled to 0-100."""
    if not series:
        return None
    below = sum(1 for x in series if x <= value)
    return 100.0 * below / len(series)
