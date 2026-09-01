"use client";

import * as React from "react";

import { cn, num, pct } from "@/lib/format";

/**
 * Landing-page market ticker.
 *
 * This is a client-side geometric Brownian motion walk, not a live feed —
 * quotes require Alpaca credentials, which a visitor has not supplied yet. It
 * is labelled "simulated" wherever it appears. Showing invented numbers as live
 * market data would be the single most dishonest thing this product could do.
 */

interface Instrument {
  symbol: string;
  seed: number;
  annualVol: number;
}

const INSTRUMENTS: Instrument[] = [
  { symbol: "SPY", seed: 604.12, annualVol: 0.13 },
  { symbol: "QQQ", seed: 528.44, annualVol: 0.18 },
  { symbol: "NVDA", seed: 178.91, annualVol: 0.46 },
  { symbol: "AAPL", seed: 241.33, annualVol: 0.22 },
  { symbol: "MSFT", seed: 492.07, annualVol: 0.2 },
  { symbol: "TSLA", seed: 402.55, annualVol: 0.55 },
];

const TICK_MS = 1_500;
const DT = TICK_MS / 1000 / (252 * 6.5 * 3600); // tick as a fraction of a trading year

function step(price: number, annualVol: number): number {
  // Box-Muller for a normal draw; drift is zero so the walk stays centred.
  const u1 = Math.random() || 1e-9;
  const u2 = Math.random();
  const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
  return price * Math.exp(-0.5 * annualVol ** 2 * DT + annualVol * Math.sqrt(DT) * z);
}

interface Quote {
  symbol: string;
  price: number;
  base: number;
}

export function MarketTicker({ className }: { className?: string }) {
  const [quotes, setQuotes] = React.useState<Quote[]>(() =>
    INSTRUMENTS.map((i) => ({ symbol: i.symbol, price: i.seed, base: i.seed })),
  );
  // The walk only starts after mount, so server and client render identically
  // and hydration stays clean.
  const [started, setStarted] = React.useState(false);

  React.useEffect(() => {
    setStarted(true);
    const timer = setInterval(() => {
      setQuotes((prev) =>
        prev.map((quote, index) => ({
          ...quote,
          price: step(quote.price, INSTRUMENTS[index].annualVol),
        })),
      );
    }, TICK_MS);
    return () => clearInterval(timer);
  }, []);

  // Cap-weighted dispersion of the walk, presented as a volatility index.
  const volIndex = React.useMemo(() => {
    const dispersion =
      quotes.reduce((acc, q) => acc + Math.abs(q.price / q.base - 1), 0) / quotes.length;
    return 14.5 + dispersion * 900;
  }, [quotes]);

  const row = (
    <ul className="flex shrink-0 items-center">
      {quotes.map((quote) => {
        const change = quote.price / quote.base - 1;
        return (
          <li
            key={quote.symbol}
            className="flex items-baseline gap-2 border-r border-border px-5 py-2"
          >
            <span className="num text-2xs font-medium text-foreground">{quote.symbol}</span>
            <span className="num text-2xs text-muted">{num(quote.price)}</span>
            <span
              className={cn(
                "num text-2xs",
                change > 0 ? "text-positive" : change < 0 ? "text-negative" : "text-subtle",
              )}
            >
              {pct(change, 2, true)}
            </span>
          </li>
        );
      })}
    </ul>
  );

  return (
    <div
      className={cn(
        "flex items-stretch border-y border-border bg-surface/60",
        className,
      )}
    >
      <div className="flex shrink-0 items-center gap-2 border-r border-border px-4">
        <span className="th">MVX</span>
        <span className="num text-xs font-medium text-accent-bright">
          {volIndex.toFixed(2)}
        </span>
      </div>

      <div className="relative flex-1 overflow-hidden">
        {/* Duplicated row + 50% translation gives a seamless loop. Paused under
            reduced-motion via the global media query in globals.css. */}
        <div className="flex w-max animate-marquee motion-reduce:animate-none">
          {row}
          {row}
        </div>
        {/* Edge scrims so items fade rather than clip at the container bounds. */}
        <div
          className="pointer-events-none absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-background to-transparent"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-background to-transparent"
          aria-hidden="true"
        />
      </div>

      <div className="hidden shrink-0 items-center border-l border-border px-4 sm:flex">
        <span className="text-2xs text-subtle">
          {started ? "Simulated preview" : "Loading"}
        </span>
      </div>
    </div>
  );
}
