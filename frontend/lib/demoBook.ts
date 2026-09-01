import { bsDelta } from "./bs";

/**
 * A single, shared toy book for the landing page's interactive widgets.
 *
 * The hero dial and the shock scrubber both drive off this, so they can never
 * disagree with each other. Every number they display is computed through
 * Black-Scholes at the shocked spot — the delta drift you see is genuine gamma,
 * not a scripted keyframe. The production book uses the Python implementation
 * in `backend/app/quant/greeks.py`; this is the same math, client-side, at one
 * contract of scale.
 */

export const DEMO = {
  underlying: "SPY",
  spot: 766.87,
  strike: 770,
  dteDays: 30,
  vol: 0.126,
  rate: 0.0425,
  contracts: 1,
  /** |Δ| at which the hedge engine engages. */
  threshold: 1.0,
} as const;

const YEARS = DEMO.dteDays / 365;

/** Option delta per share at a given spot. */
function deltaAt(spot: number): number {
  return bsDelta(spot, DEMO.strike, YEARS, DEMO.rate, DEMO.vol, true);
}

/** Share-equivalent delta of the option leg at an arbitrary spot. */
export function optionDeltaAt(spot: number): number {
  return deltaAt(spot) * DEMO.contracts * 100;
}

/**
 * One step of a geometric Brownian motion walk, used to give the hero
 * instrument ambient life. Drift is zero so the spot wanders rather than
 * trending, and the vol is the contract's own so the movement is plausible for
 * the thing being priced.
 */
export function driftSpot(spot: number, seconds: number): number {
  const dt = seconds / (252 * 6.5 * 3600);
  const u1 = Math.random() || 1e-9;
  const u2 = Math.random();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return spot * Math.exp(-0.5 * DEMO.vol ** 2 * dt + DEMO.vol * Math.sqrt(dt) * z);
}

/** Share-equivalent delta of the option leg at rest. */
export const BASE_OPTION_DELTA = deltaAt(DEMO.spot) * DEMO.contracts * 100;

/**
 * The equity hedge that neutralises the book at rest. Negative because the
 * option leg is long delta, so the offset is short stock.
 */
export const HEDGE_SHARES = -BASE_OPTION_DELTA;

export interface BookState {
  /** Fractional underlying move, e.g. 0.02 for +2%. */
  move: number;
  spot: number;
  optionDelta: number;
  netDelta: number;
  breached: boolean;
  /** Corrective order the hedge engine would submit. */
  hedgeQty: number;
  hedgeSide: "buy" | "sell";
  hedgeNotional: number;
}

/**
 * Re-price the book under a hypothetical move.
 *
 * Implied volatility is held constant (a sticky-strike assumption), matching
 * `apply_price_shock` in the backend, so the drift is purely the second-order
 * gamma effect rather than a vol-surface artefact.
 */
export function bookAt(move: number): BookState {
  const spot = DEMO.spot * (1 + move);
  const optionDelta = deltaAt(spot) * DEMO.contracts * 100;
  const netDelta = optionDelta + HEDGE_SHARES;
  const hedgeQty = Math.round(Math.abs(netDelta) * 1000) / 1000;

  return {
    move,
    spot,
    optionDelta,
    netDelta,
    breached: Math.abs(netDelta) >= DEMO.threshold,
    hedgeQty,
    hedgeSide: netDelta > 0 ? "sell" : "buy",
    hedgeNotional: hedgeQty * spot,
  };
}

/**
 * Map net delta onto a 0–1 track position.
 *
 * Piecewise on purpose: the drift band gets a generous linear slice at the
 * centre where precision matters, and everything beyond is compressed
 * logarithmically so a 20-delta excursion is still on screen rather than pinned
 * uselessly to the edge. Mirrors `deltaToPosition` in the terminal's dial.
 */
const NEUTRAL_HALF_WIDTH = 0.16;
const OUTER_HALF_WIDTH = 0.32;
const COMPRESSION_CEILING = 40;

export function deltaToTrack(netDelta: number, threshold = DEMO.threshold): number {
  if (!threshold || !Number.isFinite(netDelta)) return 0.5;
  const t = netDelta / threshold;
  const magnitude = Math.abs(t);
  if (magnitude <= 1) return 0.5 + t * NEUTRAL_HALF_WIDTH;

  const compressed =
    Math.log10(Math.min(magnitude, COMPRESSION_CEILING)) / Math.log10(COMPRESSION_CEILING);
  return 0.5 + Math.sign(t) * (NEUTRAL_HALF_WIDTH + compressed * OUTER_HALF_WIDTH);
}
