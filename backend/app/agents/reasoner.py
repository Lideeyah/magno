"""Strategy reasoning via Featherless AI (serverless open-source inference).

Featherless exposes an OpenAI-compatible ``/v1/chat/completions`` endpoint, so
this is a thin httpx client rather than another SDK dependency.

Three properties matter more than the prompt itself:

1. **The model chooses from a closed menu.** Candidates are pre-filtered through
   the risk gates *before* they are shown, and the model's reply is rejected
   unless the symbol it names is one of them. A hallucinated ticker cannot
   become an order.
2. **The model never sizes past the envelope.** Contract count is clamped, and
   the full gate chain runs again on the concrete order downstream.
3. **The model is optional.** If Featherless is unreachable, unkeyed, or returns
   junk, :func:`deterministic_policy` produces the decision instead and the
   audit log says so. The agent degrades to a quant rule, never to nothing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..broker import ChainContract, VolProfile
from ..config import settings
from ..quant.risk_gate import RiskEnvelope
from ..state_store import Strategy

log = logging.getLogger("magno.reasoner")

MAX_CANDIDATES = 14
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = """You are Magno, an autonomous options trading agent operating a \
US equity options book on Alpaca paper trading.

Your mandate: {mandate}

## The quant baseline

A deterministic policy runs alongside you using these boundaries:

{decision_rule}

Its reading for each underlying is printed below as BASELINE. Treat it as a \
well-informed colleague's opinion, not an order. You may agree, choose a \
different contract, or disagree outright — a disagreement is recorded and \
reviewed, not blocked. What you must not do is disagree *silently*: if you \
depart from the baseline, say so in your thesis and say why.

## How to read the numbers

- IV rank is the percentile of current at-the-money implied volatility against \
one year of trailing realised volatility. High = options are expensive relative \
to how much the stock actually moves.
- IV premium = implied minus realised.
  - POSITIVE premium means options are pricing MORE movement than is occurring: \
premium is rich, and selling it is the edge.
  - NEGATIVE premium means options are pricing LESS movement than is occurring: \
premium is cheap, and buying it is the edge. A negative premium is a BUY \
signal, not an absence of one. Do not read it as "unclear".
- Low IV rank together with a negative IV premium is the strongest long-volatility \
setup available. It is not a reason to stand aside.

## Hard rules

- You may ONLY select a contract from the CANDIDATES list. Every candidate has \
already passed liquidity, spread, open-interest, DTE and allocation gates. \
Selecting anything else is an invalid response.
- You choose contract, direction and size. You may not override risk limits; a \
deterministic gate re-validates your choice and will veto it.
- Position delta is hedged to zero automatically by a separate engine. Never \
factor directional conviction into your choice. Trade the volatility, not the \
direction — whether the stock rises or falls is irrelevant to you.
- Judge each underlying on its own numbers. Do not average the book into one \
view: a rich name and a cheap name are two separate opportunities, not a wash.

Respond with ONLY a JSON object, no prose and no markdown fence:
{{"action": "OPEN" | "HOLD",
  "symbol": "<exact OCC symbol from CANDIDATES, or null when HOLD>",
  "side": "buy" | "sell",
  "contracts": <integer 1-{max_contracts}>,
  "confidence": <float 0.0-1.0>,
  "thesis": "<one or two sentences naming the underlying, its IV rank, its IV \
premium, and which threshold in the decision rule it crossed>"}}"""


@dataclass
class Decision:
    action: str  # "OPEN" | "HOLD"
    symbol: str | None
    side: str
    contracts: int
    confidence: float
    thesis: str
    source: str  # "featherless" | "deterministic" | "anthropic"
    model: str | None = None
    latency_ms: int | None = None
    raw: str | None = None
    warnings: list[str] = field(default_factory=list)
    # What the deterministic policy would have done, and whether the model
    # departed from it. Recorded, never enforced.
    baseline_action: str | None = None
    baseline_symbol: str | None = None
    baseline_side: str | None = None
    diverged: bool = False
    divergence: str | None = None

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "side": self.side,
            "contracts": self.contracts,
            "confidence": self.confidence,
            "thesis": self.thesis,
            "source": self.source,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "warnings": self.warnings,
            "baseline_action": self.baseline_action,
            "baseline_symbol": self.baseline_symbol,
            "baseline_side": self.baseline_side,
            "diverged": self.diverged,
            "divergence": self.divergence,
        }


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
def _fmt_pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "n/a"


def build_user_prompt(
    *,
    strategy: Strategy,
    envelope: RiskEnvelope,
    vol_profiles: list[VolProfile],
    candidates: list[ChainContract],
    net_delta: float,
    open_positions: int,
    max_positions: int,
    buying_power: float,
    day_pnl: float,
) -> str:
    # The baseline is computed from the operator's own thresholds and shown as
    # an opinion. The model is free to depart from it; divergence is recorded
    # downstream rather than pre-empted here.
    vol_lines = []
    signals: dict[str, str] = {}
    for v in vol_profiles:
        signal = envelope.signal_for(v.iv_rank)
        if signal:
            signals[v.underlying] = signal
        rank = f"{v.iv_rank:.0f}" if v.iv_rank is not None else "n/a"
        verdict = f"BASELINE: {signal.upper()}" if signal else "BASELINE: no edge"
        vol_lines.append(
            f"- {v.underlying}: spot ${v.spot:,.2f} | ATM IV {_fmt_pct(v.atm_iv)} | "
            f"20d realised {_fmt_pct(v.realized_vol_20d)} | IV rank {rank}/100 | "
            f"IV premium {_fmt_pct(v.iv_premium)}  ->  {verdict}"
        )

    cand_lines = []
    for c in candidates:
        g = c.greeks
        signal = signals.get(c.underlying)
        marker = f" | baseline {signal}" if signal else " | baseline flat"
        cand_lines.append(
            f"- {c.symbol} | {c.underlying} {c.right} ${c.strike:g} exp {c.expiry} "
            f"({c.dte:.0f}d) | bid {c.bid:.2f} ask {c.ask:.2f} mid {c.mid:.2f} "
            f"| spread {_fmt_pct(c.spread_pct)} | OI {c.open_interest or 0:,} "
            f"| IV {_fmt_pct(c.iv)} | δ {g.delta:+.3f} Γ {g.gamma:.4f} "
            f"Θ {g.theta:.3f}/day ν {g.vega:.3f}{marker}"
        )

    if signals:
        instruction = (
            "The baseline sees an edge in: "
            + ", ".join(f"{k} ({v})" for k, v in signals.items())
            + ". Decide for yourself whether to act on one of them, act on a "
            "different name, or hold. State your reasoning either way."
        )
    else:
        instruction = (
            "The baseline sees no edge in any underlying. Decide whether you "
            "agree. If you see something it has missed, say what."
        )

    return f"""PORTFOLIO STATE
- Net portfolio delta: {net_delta:+.2f} (auto-hedged to 0)
- Open positions: {open_positions} of {max_positions} max
- Buying power: ${buying_power:,.0f}
- Day P&L: ${day_pnl:+,.2f}

VOLATILITY SURFACE
{chr(10).join(vol_lines) if vol_lines else "- no volatility data available"}

CANDIDATES (all gate-approved; you must pick from these)
{chr(10).join(cand_lines) if cand_lines else "- none passed the risk gates this cycle"}

INSTRUCTION
{instruction}

Select one action for strategy "{strategy.label}". Return JSON only."""


# --------------------------------------------------------------------------- #
# Deterministic policy (fallback and baseline)
# --------------------------------------------------------------------------- #
def deterministic_policy(
    strategy: Strategy,
    vol_profiles: list[VolProfile],
    candidates: list[ChainContract],
    max_contracts: int,
    envelope: RiskEnvelope | None = None,
) -> Decision:
    """A pure quant rule over IV rank. Runs whenever the model is unavailable,
    and serves as the baseline the model is implicitly compared against.

    High IV rank -> volatility is rich -> sell it. Low IV rank -> cheap -> buy it.
    The 35/65 dead band keeps the agent flat when there is no measurable edge.
    """
    if not candidates:
        return Decision(
            action="HOLD",
            symbol=None,
            side="buy",
            contracts=0,
            confidence=0.0,
            thesis="No contract cleared the risk gates this cycle; standing aside.",
            source="deterministic",
        )

    envelope = envelope or RiskEnvelope(
        iv_rank_sell_at=strategy.thresholds[0], iv_rank_buy_at=strategy.thresholds[1]
    )
    ranks = {v.underlying: v.iv_rank for v in vol_profiles if v.iv_rank is not None}
    premiums = {v.underlying: v.iv_premium for v in vol_profiles if v.iv_premium is not None}

    scored: list[tuple[float, str, ChainContract]] = []
    for c in candidates:
        rank = ranks.get(c.underlying)
        premium = premiums.get(c.underlying)
        if rank is None:
            continue

        # Same thresholds the LLM is given, read from the same place, so the
        # fallback can never disagree with the rule stated in the prompt.
        side = envelope.signal_for(rank)
        if side is None:
            continue
        edge = rank if side == "sell" else 100.0 - rank

        # Prefer near-the-money contracts: most vega per dollar, tightest books.
        atm_bonus = max(0.0, 20.0 * (1.0 - abs(c.moneyness) / 0.10))
        premium_bonus = (premium * 100.0) if (premium is not None and side == "sell") else 0.0
        scored.append((edge + atm_bonus + premium_bonus, side, c))

    if not scored:
        return Decision(
            action="HOLD",
            symbol=None,
            side="buy",
            contracts=0,
            confidence=0.35,
            thesis=(
                "IV rank sits inside the neutral band for every candidate; no measurable "
                "variance risk premium to capture. Holding."
            ),
            source="deterministic",
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    score, side, pick = scored[0]
    rank = ranks.get(pick.underlying)
    verb = "rich" if side == "sell" else "cheap"
    return Decision(
        action="OPEN",
        symbol=pick.symbol,
        side=side,
        contracts=max(1, min(max_contracts, 1)),
        confidence=min(0.9, 0.4 + score / 250.0),
        thesis=(
            f"{pick.underlying} IV rank {rank:.0f}/100 with ATM IV {_fmt_pct(pick.iv)} "
            f"against 20d realised — implied volatility is {verb}. "
            f"{'Selling' if side == 'sell' else 'Buying'} the {pick.dte:.0f}d "
            f"${pick.strike:g} {pick.right} to capture the spread; delta hedged to zero."
        ),
        source="deterministic",
    )


# --------------------------------------------------------------------------- #
# Featherless client
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_decision(
    payload: dict,
    candidates: list[ChainContract],
    max_contracts: int,
    source: str,
    model: str,
) -> tuple[Decision | None, list[str]]:
    """Validate a model reply into a Decision, or reject it with reasons."""
    warnings: list[str] = []
    action = str(payload.get("action", "")).upper()
    if action not in {"OPEN", "HOLD"}:
        return None, [f"unrecognised action {action!r}"]

    thesis = str(payload.get("thesis") or "").strip()[:600]
    try:
        confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence, _ = 0.5, warnings.append("confidence was not numeric; defaulted to 0.5")

    if action == "HOLD":
        return (
            Decision(
                action="HOLD",
                symbol=None,
                side="buy",
                contracts=0,
                confidence=confidence,
                thesis=thesis or "Model elected to hold.",
                source=source,
                model=model,
                warnings=warnings,
            ),
            warnings,
        )

    symbol = str(payload.get("symbol") or "").strip().upper()
    allowed = {c.symbol for c in candidates}
    if symbol not in allowed:
        # The single most important guardrail: a symbol the model invented, or
        # one that failed a gate, can never reach the order router.
        return None, [f"symbol {symbol!r} is not in the gate-approved candidate set"]

    side = str(payload.get("side", "")).lower()
    if side not in {"buy", "sell"}:
        return None, [f"unrecognised side {side!r}"]

    try:
        contracts = int(payload.get("contracts", 1))
    except (TypeError, ValueError):
        contracts, _ = 1, warnings.append("contracts was not an integer; defaulted to 1")
    if contracts < 1 or contracts > max_contracts:
        warnings.append(f"contracts {contracts} clamped to envelope max {max_contracts}")
        contracts = min(max(contracts, 1), max_contracts)

    return (
        Decision(
            action="OPEN",
            symbol=symbol,
            side=side,
            contracts=contracts,
            confidence=confidence,
            thesis=thesis or "Model returned no thesis.",
            source=source,
            model=model,
            warnings=warnings,
        ),
        warnings,
    )


async def _call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float,
) -> tuple[str, int]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                # Low temperature: this is a risk decision, not a creative one.
                "temperature": 0.2,
                "max_tokens": 600,
            },
        )
        response.raise_for_status()
        body = response.json()
    content = body["choices"][0]["message"]["content"]
    usage = body.get("usage", {}) or {}
    return content, int(usage.get("total_tokens", 0))


async def _call_anthropic(
    *, api_key: str, model: str, system: str, user: str, timeout: float
) -> tuple[str, int]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 600,
                "temperature": 0.2,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        response.raise_for_status()
        body = response.json()
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    usage = body.get("usage", {}) or {}
    return text, int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))


async def reason(
    *,
    strategy: Strategy,
    envelope: RiskEnvelope,
    vol_profiles: list[VolProfile],
    candidates: list[ChainContract],
    net_delta: float,
    open_positions: int,
    max_positions: int,
    buying_power: float,
    day_pnl: float,
    max_contracts: int,
) -> Decision:
    """Ask the configured model for a decision; fall back to the quant rule."""
    import time

    shortlist = candidates[:MAX_CANDIDATES]
    baseline = deterministic_policy(strategy, vol_profiles, shortlist, max_contracts, envelope)

    system = SYSTEM_PROMPT.format(
        mandate=strategy.mandate,
        decision_rule=envelope.decision_rule,
        max_contracts=max_contracts,
    )
    user = build_user_prompt(
        strategy=strategy,
        envelope=envelope,
        vol_profiles=vol_profiles,
        candidates=shortlist,
        net_delta=net_delta,
        open_positions=open_positions,
        max_positions=max_positions,
        buying_power=buying_power,
        day_pnl=day_pnl,
    )

    providers: list[tuple[str, str, Any]] = []
    if settings.featherless_api_key:
        providers.append(("featherless", settings.featherless_model, None))
    if settings.anthropic_api_key:
        providers.append(("anthropic", settings.anthropic_model, None))

    accumulated_warnings: list[str] = []
    for source, model, _ in providers:
        started = time.perf_counter()
        try:
            if source == "featherless":
                content, _tokens = await _call_openai_compatible(
                    base_url=settings.featherless_base_url,
                    api_key=settings.featherless_api_key or "",
                    model=model,
                    system=system,
                    user=user,
                    timeout=settings.featherless_timeout_s,
                )
            else:
                content, _tokens = await _call_anthropic(
                    api_key=settings.anthropic_api_key or "",
                    model=model,
                    system=system,
                    user=user,
                    timeout=settings.featherless_timeout_s,
                )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:200] if exc.response is not None else str(exc)
            accumulated_warnings.append(f"{source} HTTP {exc.response.status_code}: {detail}")
            log.warning("%s call failed: %s", source, detail)
            continue
        except Exception as exc:  # network, timeout, malformed body
            accumulated_warnings.append(f"{source} unreachable: {type(exc).__name__}: {exc}")
            log.warning("%s call failed: %s", source, exc)
            continue

        latency_ms = int((time.perf_counter() - started) * 1000)
        payload = _extract_json(content)
        if payload is None:
            accumulated_warnings.append(f"{source} returned unparseable output")
            continue

        decision, reasons = _coerce_decision(payload, shortlist, max_contracts, source, model)
        if decision is None:
            accumulated_warnings.extend(f"{source} rejected: {r}" for r in reasons)
            continue

        decision.latency_ms = latency_ms
        decision.raw = content[:2000]
        decision.warnings = accumulated_warnings + decision.warnings
        return _attach_baseline(decision, baseline)

    fallback = baseline
    if not providers:
        accumulated_warnings.append(
            "No FEATHERLESS_API_KEY configured; running the deterministic quant policy."
        )
    fallback.warnings = accumulated_warnings
    return fallback


def _attach_baseline(decision: Decision, baseline: Decision) -> Decision:
    """Record what the quant policy would have done and how the model differed.

    Divergence is information, not an error. A model that only ever echoes the
    baseline adds nothing; one that departs from it needs to be visible when it
    does, so the operator can judge whether its reasoning was better or worse.
    """
    decision.baseline_action = baseline.action
    decision.baseline_symbol = baseline.symbol
    decision.baseline_side = baseline.side if baseline.action == "OPEN" else None

    if decision.action != baseline.action:
        decision.diverged = True
        decision.divergence = (
            f"model chose {decision.action}, quant baseline would "
            f"{baseline.action}"
            + (
                f" {baseline.side} {baseline.symbol}"
                if baseline.action == "OPEN"
                else ""
            )
        )
    elif decision.action == "OPEN" and decision.side != baseline.side:
        decision.diverged = True
        decision.divergence = (
            f"model chose {decision.side}, quant baseline would {baseline.side}"
        )
    elif decision.action == "OPEN" and decision.symbol != baseline.symbol:
        decision.diverged = True
        decision.divergence = (
            f"same direction, different contract: model {decision.symbol} vs "
            f"baseline {baseline.symbol}"
        )
    return decision
