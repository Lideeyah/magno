import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Consistent precision per unit, applied everywhere. Mixed decimal places
 * across a view is one of the fastest ways to make numbers look untrustworthy.
 */

const EMPTY = "—";

export function usd(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Signed dollars, for P&L. The sign is always explicit. */
export function usdSigned(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${usd(Math.abs(value), decimals)}`;
}

/** Compact dollars for headline figures: $102.4k, $1.28M. */
export function usdCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}k`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function pct(
  value: number | null | undefined,
  decimals = 2,
  signed = false,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  const sign = signed && value > 0 ? "+" : signed && value < 0 ? "−" : "";
  return `${sign}${(Math.abs(value) * 100).toFixed(decimals)}%`;
}

/** Greeks are always 3dp with an explicit sign. */
export function greek(value: number | null | undefined, decimals = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(decimals)}`;
}

export function num(
  value: number | null | undefined,
  decimals = 2,
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function int(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return Math.round(value).toLocaleString("en-US");
}

export function clockTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EMPTY;
  return d.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return EMPTY;
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

/** Human-readable expiry: 2025-09-19 → 19 Sep 25. */
export function expiryLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

/** Tone classes for a signed value. Grey at exactly zero — no false signal. */
export function toneFor(value: number, invert = false): string {
  if (value === 0 || Number.isNaN(value)) return "text-muted";
  const positive = invert ? value < 0 : value > 0;
  return positive ? "text-positive" : "text-negative";
}

export function occLabel(symbol: string): string {
  const m = /^([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol);
  if (!m) return symbol;
  const [, root, yy, mm, dd, cp, strike] = m;
  const price = Number(strike) / 1000;
  return `${root} ${expiryLabel(`20${yy}-${mm}-${dd}`)} ${price % 1 === 0 ? price.toFixed(0) : price.toFixed(2)}${cp}`;
}
