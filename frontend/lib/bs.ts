/**
 * Minimal Black-Scholes for the landing-page demonstration only.
 *
 * The authoritative implementation lives in `backend/app/quant/greeks.py` and
 * is what actually prices the book. This exists so the marketing preview shows
 * a real gamma effect rather than a scripted animation — nothing in the
 * terminal uses it.
 */

function erf(x: number): number {
  // Abramowitz & Stegun 7.1.26 — accurate to ~1.5e-7, ample for a preview.
  const sign = Math.sign(x);
  const a = [0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429];
  const p = 0.3275911;
  const t = 1 / (1 + p * Math.abs(x));
  const y =
    1 -
    ((((a[4] * t + a[3]) * t + a[2]) * t + a[1]) * t + a[0]) * t * Math.exp(-x * x);
  return sign * y;
}

export function normCdf(x: number): number {
  return 0.5 * (1 + erf(x / Math.SQRT2));
}

export function bsDelta(
  spot: number,
  strike: number,
  years: number,
  rate: number,
  vol: number,
  isCall: boolean,
): number {
  const t = Math.max(years, 1 / (365 * 24));
  const sigma = Math.max(vol, 1e-4);
  const d1 =
    (Math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * t) / (sigma * Math.sqrt(t));
  return isCall ? normCdf(d1) : normCdf(d1) - 1;
}
