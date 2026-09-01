# Magno

**Autonomous options trading and delta-neutral hedging on Alpaca paper trading.**

Magno runs an options book without a human in the loop. A language model served
by **Featherless AI** proposes the trade; nine deterministic risk gates decide
whether it happens; portfolio delta is pulled back to zero continuously with
fractional equity orders.

Built for the Alpaca AI Trading Agents Hackathon — *Options Alpha Agents* track.

---

## The one-paragraph version

Every 60 seconds the agent scans SPY, QQQ, NVDA and AAPL: it pulls live option
chains, inverts implied volatility from the NBBO mid, and ranks each name by
where its ATM IV sits against a year of realised volatility. Contracts that pass
every pre-trade gate become a closed menu presented to the model — which can
only pick from that menu, so a hallucinated symbol can never become an order.
The chosen trade is re-gated against a *fresh* quote at submit time and sent as
a marketable limit. Separately, every 5 seconds, the hedge engine recomputes
share-equivalent delta per underlying and neutralises anything past the drift
cap with fractional equity orders sized to three decimal places.

**The model proposes. Arithmetic disposes.**

---

## Quick start

Two terminals. The backend needs no credentials to boot — you supply Alpaca
paper keys through the onboarding UI.

### 1. Backend

```bash
cd backend
python3.11 -m venv .venv && source .venv/bin/activate   # or: uv venv --python 3.11 .venv
pip install -r requirements.txt
cp .env.example .env        # add FEATHERLESS_API_KEY for LLM reasoning (optional)
uvicorn app.main:app --reload --port 8000
```

Check it: `curl localhost:8000/health` · API docs at `localhost:8000/docs`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**, click **Connect paper account**, and paste your
Alpaca **paper** API key and secret. Magno validates them against
`paper-api.alpaca.markets`, confirms the $100k baseline, and drops you into the
terminal.

> If the backend is not on port 8000, set `NEXT_PUBLIC_MAGNO_API` in
> `frontend/.env.local`.

### 3. Run the tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q          # 136 passing
```

---

## What is actually running

```
┌────────────────────────────────────────────────────────────────┐
│  Next.js 15 terminal ── WebSocket /ws/telemetry (1 Hz frames   │
│                          + instant event pushes)               │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│  FastAPI                                                       │
│                                                                │
│   autopilot.py ── two cadences in one task:                    │
│     5s   hedge tick    (deterministic, no model in the path)   │
│     60s  reasoning tick (scan → model → gates → execute)       │
│                                                                │
│   MagnoTools ── the agent's four capabilities                  │
│     scan_market_volatility · get_account_greeks                │
│     execute_options_strategy · rebalance_portfolio             │
│     ↑ same implementation drives the in-process loop AND the   │
│       stdio MCP server. There is no privileged path.           │
│                                                                │
│   quant/  greeks.py · risk_gate.py · hedge_engine.py           │
│           pure functions, no I/O, 111 unit tests               │
└───────────┬─────────────────────────────┬──────────────────────┘
            │                             │
   Featherless AI                  Alpaca paper API
   (OpenAI-compatible)             (paper=True, always)
```

### The risk gates

Pure functions over plain data — no network, no clock, no LLM. They run
identically for autonomous orders, terminal orders, and external MCP clients.

| Gate | Rule | Why |
|---|---|---|
| `SPREAD_TOO_WIDE` | `(ask − bid) / mid ≤ 5%` | An option you cannot exit is one you cannot risk-manage |
| `ALLOC_EXCEEDS_CAP` | notional ≤ 10% of buying power | No single contract can take the book down |
| `DAILY_LOSS_HALT` | day drawdown < 5% | Stops new risk. **Hedging deliberately continues** |
| `CONCENTRATION_CAP` | ≤ 6 open positions | Bounds correlated exposure |
| `OI_TOO_THIN` | open interest ≥ 100 | Thin books gap through your exit |
| `DTE_TOO_NEAR/FAR` | 5 ≤ DTE ≤ 60 | Avoids pin risk; preserves capital efficiency |
| `PRICE_TOO_LOW/HIGH` | $0.10 ≤ mid ≤ $40 | No lottery tickets, no capital hogs |
| `IV_UNSOLVABLE` | implied vol must invert | A quote outside arbitrage bounds is a broken quote |
| `MARKET_CLOSED` | US equity hours | No new risk outside RTH |

Every verdict — pass, warn and reject — is streamed to the execution ledger with
the observed value and the limit, so any decision can be replayed from the UI.

### The hedge engine

Net delta is the share-equivalent sum:

```
Δ_net = Σ(option δ × contracts × 100) + Σ(shares held)
```

Two decisions worth calling out:

**Exposure is bucketed per underlying, then summed.** The dial shows portfolio
delta, but a hedge only ever executes against the underlying that produced the
drift. A long SPY call and a long QQQ put can net to zero portfolio delta while
each name carries 60 delta — hedging on the portfolio number alone silently
converts a neutral book into a cross-asset basis bet. There is a test for this.

**Hedges are fractional.** Rounding to whole shares leaves up to 0.5 delta of
residual per underlying, which on a four-name book is most of the 1.0 trigger.
Alpaca accepts fractional market DAY orders, so Magno neutralises to three
decimals and converges to ~0.

### Greeks

Alpaca returns Greeks only on OPRA-subscribed accounts and they are routinely
`null` on paper, so Magno computes its own: Newton-Raphson implied-vol inversion
(seeded with Brenner-Subrahmanyam, bisection fallback in the wings) then
analytic Black-Scholes-Merton Greeks. Alpaca's values are preferred whenever
they are actually present.

The math is tested against closed-form identities rather than golden values:
put-call parity, delta parity, `Γ_call == Γ_put`, and central-difference checks
of delta, gamma and vega against the pricer itself.

---

## Featherless AI integration

Featherless serves the strategy reasoner over its OpenAI-compatible endpoint.
Set `FEATHERLESS_API_KEY` in `backend/.env`; the model is configurable via
`FEATHERLESS_MODEL` (default `Qwen/Qwen2.5-72B-Instruct`).

Three properties make this safe to run unattended:

1. **Closed menu.** Candidates are gate-filtered *before* being shown, and a
   reply naming any other symbol is rejected outright.
2. **Clamped sizing.** Contract count is bounded by the envelope, and the full
   gate chain re-runs on the concrete order.
3. **Optional.** If Featherless is unreachable or returns junk, a deterministic
   IV-rank policy produces the decision instead and the ledger records why. The
   agent degrades to a quant rule, never to nothing.

`/health` reports which reasoner is live.

---

## MCP server

The same four tools are published over stdio:

```bash
cd backend
ALPACA_API_KEY=... ALPACA_SECRET_KEY=... .venv/bin/python -m app.agents.alpaca_mcp
```

Register it with any MCP client (`mcp.json` at the repo root is a ready-made
Claude Desktop entry — fill in your paths and paper keys):

```json
{
  "mcpServers": {
    "magno-alpaca": {
      "command": "/absolute/path/to/Magno/backend/.venv/bin/python",
      "args": ["-m", "app.agents.alpaca_mcp"],
      "cwd": "/absolute/path/to/Magno/backend",
      "env": { "ALPACA_API_KEY": "PK...", "ALPACA_SECRET_KEY": "..." }
    }
  }
}
```

An MCP client calling `execute_options_strategy` hits exactly the same gate
chain as the autonomous loop, because it is the same function.

---

## The shock simulator

The terminal's **Shock** drawer re-prices your live book at a hypothetical spot
(±10%) through Black-Scholes with implied vol held constant. The delta drift
that appears is the genuine gamma effect on your real positions — not an
animation.

While a shock is active the hedge engine **computes and logs** its corrective
order but does not submit it. The move did not happen, and a real fill against a
simulated price would corrupt the P&L the agent is judged on. Clear the shock to
resume live hedging.

This is the fastest way to see the whole loop: apply +2% to SPY, watch the dial
break the drift cap and go cobalt, and read the corrective order in the ledger.

---

## Security notes

- The Alpaca trading client is constructed with `paper=True` unconditionally.
  There is no code path in Magno that reaches a live endpoint.
- Credentials submitted at onboarding are held in **process memory only** —
  never written to disk, never logged, never returned to the client. A session
  dies with the process, and `End` clears it immediately.
- The browser stores only an opaque session id, never the keys themselves.

---

## Layout

```
backend/
  app/
    main.py              FastAPI app + telemetry websocket
    config.py            settings and risk defaults
    broker.py            typed async adapter over alpaca-py
    frame.py             1 Hz telemetry frame composition
    events.py            the execution audit ledger
    state_store.py       in-memory sessions
    quant/
      greeks.py          BSM pricing, IV inversion, OCC symbology
      risk_gate.py       the nine deterministic gates
      hedge_engine.py    delta aggregation, hedge intents, shock repricing
    agents/
      reasoner.py        Featherless client + deterministic fallback policy
      alpaca_mcp.py      the four tools + stdio MCP server
      autopilot.py       the autonomous loop
    routers/             telemetry · scan · orders
  tests/                 136 tests
frontend/
  app/                   landing · onboarding · terminal
  components/            DeltaMagneticDial · GreeksTelemetry · OptionsChainTable
                         ExecutionAuditStream · OrderSimulationModal · …
  lib/                   api client · telemetry socket · formatting
brand.md                 palette, typography and voice
```

---

Paper trading only. Not investment advice.
