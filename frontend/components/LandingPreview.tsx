"use client";

import * as React from "react";

import { bsDelta } from "@/lib/bs";
import { cn, clockTime, greek, num } from "@/lib/format";

import { deltaToPosition } from "./DeltaMagneticDial";
import { Badge, StatusPip } from "./ui";

/**
 * A working miniature of the hedge loop, running client-side.
 *
 * A long SPY call is priced through Black-Scholes on every tick. As the
 * simulated spot walks, gamma pushes the position's delta away from the equity
 * hedge that neutralised it, and once |net Δ| crosses 1.0 the loop "sells"
 * fractional shares to pull it back to zero. The drift and the correction are
 * both computed, not scripted — it is the same mechanism the backend runs, at
 * toy scale, so the landing page demonstrates the product rather than
 * illustrating it.
 */

const STRIKE = 605;
const VOL = 0.14;
const RATE = 0.0425;
const YEARS = 32 / 365;
const CONTRACTS = 1;
const THRESHOLD = 1.0;
const TICK_MS = 900;
const MAX_LOG = 7;

interface LogLine {
  id: number;
  ts: string;
  kind: "drift" | "hedge" | "scan";
  text: string;
}

export function LandingPreview({ className }: { className?: string }) {
  const [spot, setSpot] = React.useState(604.12);
  const [shares, setShares] = React.useState(() => {
    const d = bsDelta(604.12, STRIKE, YEARS, RATE, VOL, true);
    return -d * CONTRACTS * 100; // start delta-neutral
  });
  const [log, setLog] = React.useState<LogLine[]>([]);
  const [hedging, setHedging] = React.useState(false);
  const [hedgeCount, setHedgeCount] = React.useState(0);
  const [mounted, setMounted] = React.useState(false);
  const idRef = React.useRef(0);

  const optionDelta = bsDelta(spot, STRIKE, YEARS, RATE, VOL, true);
  const netDelta = optionDelta * CONTRACTS * 100 + shares;

  const push = React.useCallback((kind: LogLine["kind"], text: string) => {
    idRef.current += 1;
    setLog((prev) =>
      [
        ...prev,
        { id: idRef.current, ts: new Date().toISOString(), kind, text },
      ].slice(-MAX_LOG),
    );
  }, []);

  React.useEffect(() => {
    setMounted(true);
    push("scan", "Agent online · SPY 605C 32d · delta-neutral at open");
  }, [push]);

  React.useEffect(() => {
    const timer = setInterval(() => {
      setSpot((previous) => {
        // Larger steps than reality so the loop visibly cycles on a landing page.
        const drift = (Math.random() - 0.5) * 1.35;
        return Math.max(560, Math.min(650, previous + drift));
      });
    }, TICK_MS);
    return () => clearInterval(timer);
  }, []);

  // Hedge whenever the drift cap is breached.
  React.useEffect(() => {
    if (Math.abs(netDelta) < THRESHOLD) return;

    const qty = Math.round(Math.abs(netDelta) * 1000) / 1000;
    const side = netDelta > 0 ? "SELL" : "BUY";

    setHedging(true);
    push("drift", `|Δ| ${Math.abs(netDelta).toFixed(3)} ≥ ${THRESHOLD.toFixed(2)} drift cap`);
    push("hedge", `${side} ${qty.toFixed(3)} SPY → Δ ${greek(0)}`);
    setShares((previous) => previous + (netDelta > 0 ? -qty : qty));
    setHedgeCount((n) => n + 1);

    const timer = setTimeout(() => setHedging(false), 700);
    return () => clearTimeout(timer);
  }, [netDelta, push]);

  const position = deltaToPosition(netDelta, THRESHOLD);

  return (
    <div
      className={cn(
        "panel overflow-hidden",
        hedging && "border-accent-bright/50",
        className,
      )}
    >
      <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <StatusPip tone={hedging ? "accent" : "positive"} pulse={hedging} />
          <span className="text-xs font-medium text-foreground">Hedge loop</span>
          <span className="text-2xs text-subtle">simulated</span>
        </div>
        <div className="flex items-center gap-3 text-2xs">
          <span className="num text-muted">SPY {num(spot)}</span>
          <span className="num text-subtle">{hedgeCount} hedges</span>
        </div>
      </header>

      <div className="px-4 py-4">
        <div className="flex items-baseline justify-between">
          <span className="th">Net portfolio delta</span>
          <span
            className={cn(
              "num text-xl font-medium transition-colors duration-200 ease-move",
              hedging ? "text-accent-bright" : "text-foreground",
            )}
          >
            {mounted ? greek(netDelta) : greek(0)}
          </span>
        </div>

        {/* Same scale mapping as the production dial. */}
        <div className="relative mt-3 h-8">
          <div className="absolute inset-x-0 top-3.5 h-1.5 rounded-full bg-surface-raised ring-1 ring-inset ring-border" />
          <div
            className={cn(
              "absolute top-3.5 h-1.5 rounded-full transition-colors duration-200 ease-move",
              hedging ? "bg-accent-dim/50" : "bg-positive/20",
            )}
            style={{ left: "32%", width: "36%" }}
            aria-hidden="true"
          />
          <div className="absolute left-1/2 top-1.5 h-5 w-px bg-subtle" aria-hidden="true" />
          <div
            className="absolute top-0 h-8 transition-transform duration-300 ease-move will-change-transform"
            style={{ left: `${position * 100}%`, transform: "translateX(-50%)" }}
            aria-hidden="true"
          >
            <div
              className={cn(
                "h-8 w-0.5 rounded-full transition-colors duration-200 ease-move",
                hedging ? "bg-accent-bright" : "bg-foreground",
              )}
            />
          </div>
        </div>

        <div className="mt-1 flex justify-between text-2xs text-subtle">
          <span className="num">−1.00</span>
          <span className="num">0.000</span>
          <span className="num">+1.00</span>
        </div>

        <dl className="mt-4 grid grid-cols-3 gap-3 border-t border-border pt-3">
          <div>
            <dt className="th">Option Δ</dt>
            <dd className="num mt-0.5 text-xs text-foreground">
              {mounted ? greek(optionDelta) : "—"}
            </dd>
          </div>
          <div>
            <dt className="th">Hedge shares</dt>
            <dd className="num mt-0.5 text-xs text-foreground">
              {mounted ? num(shares, 3) : "—"}
            </dd>
          </div>
          <div>
            <dt className="th">Status</dt>
            <dd className="mt-0.5">
              {hedging ? (
                <Badge tone="accent">Hedging</Badge>
              ) : (
                <Badge tone="positive">Neutral</Badge>
              )}
            </dd>
          </div>
        </dl>
      </div>

      <div className="border-t border-border bg-background/40 px-4 py-3">
        <ul className="space-y-1" aria-live="off">
          {log.length === 0 ? (
            <li className="text-2xs text-subtle">Initialising…</li>
          ) : (
            log.map((line) => (
              <li key={line.id} className="flex gap-2 text-2xs animate-fade-up">
                <span className="num shrink-0 text-subtle">{clockTime(line.ts)}</span>
                <span
                  className={cn(
                    "num shrink-0 w-12",
                    line.kind === "hedge"
                      ? "text-accent-bright"
                      : line.kind === "drift"
                        ? "text-warning"
                        : "text-subtle",
                  )}
                >
                  {line.kind.toUpperCase()}
                </span>
                <span className="min-w-0 flex-1 truncate text-muted">{line.text}</span>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}
