# Magno

**Autonomous volatility harvesting with a magnetic delta restoring force.**

Magno runs an options book on Alpaca paper trading and holds it delta-neutral in real time. It scans the volatility surface, prices every contract locally, proposes trades through a bounded language model, and refuses to route anything that fails nine deterministic arithmetic gates. Every decision it makes is written to an append-only ledger you can read top to bottom and reconstruct without opening the source.

**Live app →** https://magno-lideeyahs-projects.vercel.app
**API →** https://magno-v387.onrender.com/health
**Repository →** https://github.com/Lideeyah/magno

---

## The idea

An options book drifts. Every fill, every tick of the underlying, every hour of decay moves net delta away from zero, and a book that is nominally "market neutral" quietly becomes a directional bet nobody chose to make.

Magno treats that drift the way a magnet treats a displaced needle: as something with a restoring force acting on it. Delta is measured continuously per underlying, and the moment it leaves a bounded envelope an equity hedge pulls it back. The force is arithmetic, not judgement.

---

## Architectural pillars

### 1. Magnetic delta restoring force

Net exposure is computed in share-equivalent terms:

```
Δ_net = Σ(option δ × contracts × 100) + Σ(shares)
```

**Bucketed per underlying, never portfolio-wide.** A portfolio-level delta of zero can hide a long NVDA position against a short SPY one — a basis bet nobody sized. Each underlying is hedged against its own delta.

**A bounded envelope, not a target.** Hedging to exactly zero on every tick pays the spread continuously and achieves nothing; the drift cap (±8.0Δ in the tuned configuration) is the width of the band the hedger defends. This was set by measurement, not assertion: at ±1.0Δ the book took 11 fills and $81,013 of turnover; at ±8.0Δ, 6 fills and $74,036 — roughly 45% fewer fills for the same neutrality.

**Fractional equity hedging, with the broker's real constraints encoded.** Two Alpaca rules shape the sizing, and both were established against the live API rather than inferred from documentation:

- Fractional shares **cannot be sold short** — `42210000 fractional orders cannot be sold short`. A short hedge is floored to whole shares.
- An order **may not cross through zero** — `40310000 insufficient qty available`. Selling out of a long position stops at flat and a second order establishes the short.

```python
def hedge_quantity(net_delta: float, equity_held: float) -> float:
    qty = abs(net_delta)
    if net_delta <= 0:                       # buying
        if equity_held < 0 and qty > -equity_held:
            return round_qty(-equity_held)   # buy back to flat, no further
        return round_qty(qty)
    if equity_held - qty >= 0:
        return round_qty(qty)                # selling out of a long
    if equity_held > 0:
        return round_qty(equity_held)        # sell to flat, never through it
    return float(math.floor(qty))            # whole-share short
```

**In-flight orders count.** A hedge that has been submitted but not filled is still exposure the next cycle must know about, or the agent stacks duplicate hedges against a delta reading that is already being corrected. Effective delta is `Δ_positions + Δ_in_flight`.

### 2. Bounded AI reasoning

Featherless AI (**Qwen/Qwen2.5-72B-Instruct**) reads the volatility surface and proposes an action. It cannot execute anything.

- **Closed menu.** The model selects from a fixed schema of actions on a fixed universe of contracts. There is no free-text path to the broker.
- **The quant policy is the baseline.** Every prompt carries the deterministic policy's own recommendation. When the model diverges, the divergence is recorded in the ledger — it is not silently accepted or silently discarded.
- **Arithmetic disposes.** The model's proposal is an input to the risk gates, never a bypass of them. A rejected proposal is logged with the gate that rejected it.
- **It degrades, it does not fail.** With no Featherless key the agent falls back to the deterministic policy and keeps trading.

Greeks are computed locally with Black-Scholes-Merton and a Newton-Raphson IV inversion (Brenner-Subrahmanyam seed, bisection fallback) rather than read from the broker — Alpaca returns `null` Greeks on unsubscribed paper accounts, so a book that trusted the API would be flying blind.

### 3. Nine deterministic risk gates

Pure functions. No model output reaches the broker without clearing all of them.

| Gate | Rule |
|---|---|
| Spread ceiling | bid-ask ≤ 5% of mid |
| Allocation cap | ≤ 10% of buying power per position |
| Concentration | bounded open positions per underlying |
| DTE window | entry ≥ 28 days, ≤ 60 |
| Liquidity | open interest ≥ 100 |
| Price band | $0.10 ≤ premium ≤ $40.00 |
| Delta drift | hedge when \|Δ\| exceeds the envelope |
| Daily loss breaker | halt at −5% |
| Market hours | no routing into a closed session |

The DTE window and the exit engine are checked against each other at onboarding. They once overlapped, and the result was a 17.2-DTE put bought at 4.85 and stopped out at 4.75 one second later — a round-trip of the spread for no exposure, repeating once a minute. `validate_dte_against_exit` now makes that state unreachable.

**Exit rules are asymmetric by construction.** A short option can lose many multiples of the premium collected, so it stops at −100%. A long option cannot lose more than it cost, so a −100% stop would never fire; it stops at −50%. Both take profit at +50% and time-stop at 21 DTE.

---

## Live telemetry

- **1 Hz WebSocket** carrying full frames plus events pushed the instant a decision is logged, merged by sequence number so a reconnect cannot duplicate rows.
- **Per-underlying Greeks isolation** — delta, gamma, theta, vega bucketed rather than aggregated into a single misleading number.
- **Append-only execution ledger** recording every scan, completion, gate verdict, order, fill and hedge, with `SUBMITTED` and `FILLED` distinguished so an unfilled hedge is never reported as a completed one.
- **Sessions survive restarts.** Credentials live in process memory and die with the process — which on a free-tier host happens on every idle spin-down. The server issues a Fernet-encrypted resume token the browser holds and posts back; only the server can read it, and a session rebuilds without the operator re-entering keys.

Credentials are never written to disk, never logged, and never returned to the client. The Alpaca client is constructed `paper=True` unconditionally — there is no live-trading code path.

---

## Quickstart

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add FEATHERLESS_API_KEY; Alpaca keys are entered in the browser
uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev                   # http://localhost:3000
```

**Tests**

```bash
cd backend && .venv/bin/python -m pytest -q     # 302 passed
cd frontend && npm run typecheck
```

**Environment**

| Variable | Purpose |
|---|---|
| `FEATHERLESS_API_KEY` | Reasoner. Without it the deterministic policy runs alone. |
| `MAGNO_SESSION_KEY` | Fernet key for resume tokens. Must be stable across restarts. |
| `MAGNO_CORS_ORIGINS` | Comma-separated frontend origins. |
| `NEXT_PUBLIC_MAGNO_API` | Backend URL. Inlined at **build** time. |

Generate a session key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Onboarding.** Open the app, paste **paper** keys from the Alpaca Paper Trading dashboard, set the risk envelope, and the terminal connects. Keys go from the browser to the backend's memory and no further.

---

## Deployment

Frontend on Vercel, backend as a container on Render (`./Dockerfile` at the repo root; `PORT` is honoured from the environment).

One property worth stating plainly: on a free tier the backend spins down when idle, and the first request after that takes 30–60 seconds. Sessions rebuild from the resume token, but the cold start is real.

---

## Stack

FastAPI · Alpaca (paper) · Featherless AI · MCP · Next.js 15 · React 19 · Tailwind · Recharts
