"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import * as React from "react";

import {
  DEMO,
  deltaToTrack,
  driftSpot,
  optionDeltaAt,
} from "@/lib/demoBook";
import { cn, greek, num, usd } from "@/lib/format";

/**
 * The hero instrument — a live desk, not a widget waiting to be clicked.
 *
 * A market runs continuously underneath it: the spot walks on a real GBM step,
 * the option is re-priced through Black-Scholes on every tick, and gamma pushes
 * net delta off zero on its own. When |Δ| crosses the drift cap the engine
 * fires a fractional hedge and pulls exposure back. Nobody has to touch it for
 * the loop to be visible.
 *
 * The shock buttons don't start the machine — they perturb a machine that is
 * already running, which is what makes the correction legible as *behaviour*
 * rather than as an animation someone triggered.
 */

const SNAP = { type: "spring" as const, stiffness: 400, damping: 30 };
const RECOVER = { type: "spring" as const, stiffness: 110, damping: 22 };
const TICK_MS = 1_100;
const MAX_LEDGER = 3;

interface LedgerLine {
  id: number;
  side: "buy" | "sell";
  qty: number;
  notional: number;
  cause: string;
}

export function HeroDeltaDial({ className }: { className?: string }) {
  const reduceMotion = useReducedMotion();

  // Explicit `number`: DEMO is `as const`, so inference would pin this to the
  // literal 766.87 and reject every subsequent tick.
  const [spot, setSpot] = React.useState<number>(DEMO.spot);
  const [hedgeShares, setHedgeShares] = React.useState(() => -optionDeltaAt(DEMO.spot));
  const [ledger, setLedger] = React.useState<LedgerLine[]>([]);
  const [hedgeCount, setHedgeCount] = React.useState(0);
  const [flash, setFlash] = React.useState(false);
  // Rendered only after mount so server and client markup match exactly.
  const [live, setLive] = React.useState(false);

  const idRef = React.useRef(0);
  const causeRef = React.useRef("drift");

  const netDelta = optionDeltaAt(spot) + hedgeShares;
  const breached = live && Math.abs(netDelta) >= DEMO.threshold;

  // --- the market runs on its own ---------------------------------------- //
  React.useEffect(() => {
    setLive(true);
    if (reduceMotion) return; // a self-animating instrument is still motion
    const timer = setInterval(() => {
      causeRef.current = "drift";
      setSpot((previous) => driftSpot(previous, 90));
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [reduceMotion]);

  // --- the engine corrects what the market does --------------------------- //
  React.useEffect(() => {
    if (!live || Math.abs(netDelta) < DEMO.threshold) return;

    setFlash(true);
    const qty = Math.round(Math.abs(netDelta) * 1000) / 1000;
    const side: "buy" | "sell" = netDelta > 0 ? "sell" : "buy";
    const cause = causeRef.current;

    // Let the breach be readable before it is corrected.
    const timer = setTimeout(
      () => {
        idRef.current += 1;
        setLedger((prev) =>
          [
            { id: idRef.current, side, qty, notional: qty * spot, cause },
            ...prev,
          ].slice(0, MAX_LEDGER),
        );
        setHedgeShares((prev) => prev + (side === "sell" ? -qty : qty));
        setHedgeCount((n) => n + 1);
        setFlash(false);
      },
      reduceMotion ? 0 : 620,
    );
    return () => clearTimeout(timer);
  }, [netDelta, live, spot, reduceMotion]);

  const shock = (move: number, label: string) => {
    causeRef.current = label;
    setSpot((previous) => previous * (1 + move));
  };

  const reset = () => {
    causeRef.current = "reset";
    setSpot(DEMO.spot);
    setHedgeShares(-optionDeltaAt(DEMO.spot));
    setLedger([]);
    setHedgeCount(0);
    setFlash(false);
  };

  const track = deltaToTrack(live ? netDelta : 0);

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-lg border bg-surface transition-colors duration-200",
        flash ? "border-negative/40" : "border-white/[0.08]",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.08] px-4 py-2.5">
        <span className="num text-2xs uppercase tracking-[0.14em] text-subtle">
          Delta equilibrium
        </span>
        <div className="flex items-center gap-3">
          <span className="num text-2xs text-subtle">{hedgeCount} hedges</span>
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={flash ? "breach" : "ok"}
              initial={reduceMotion ? false : { opacity: 0, y: -3 }}
              animate={{ opacity: 1, y: 0 }}
              exit={reduceMotion ? undefined : { opacity: 0, y: 3 }}
              transition={{ duration: 0.12 }}
              className={cn(
                "num text-2xs uppercase tracking-[0.14em]",
                flash ? "text-negative" : "text-subtle",
              )}
            >
              {flash ? "Hedge required" : "Neutral"}
            </motion.span>
          </AnimatePresence>
        </div>
      </div>

      <div className="px-5 py-6">
        {/* Reading */}
        <div className="flex items-baseline justify-between">
          <span
            className={cn(
              "num text-4xl font-medium tabular-nums transition-colors duration-150",
              flash ? "text-negative" : "text-foreground",
            )}
          >
            {greek(live ? netDelta : 0)}
          </span>
          <span className="num text-2xs tabular-nums text-subtle">
            {DEMO.underlying} {num(spot)}
          </span>
        </div>

        {/* Track */}
        <div className="relative mt-6 h-10">
          <div className="absolute inset-x-0 top-4 h-px bg-white/[0.10]" />
          <div
            className={cn(
              "absolute top-[13px] h-[3px] transition-colors duration-200",
              flash ? "bg-negative/30" : "bg-accent/40",
            )}
            style={{ left: "34%", width: "32%" }}
            aria-hidden="true"
          />
          {[34, 66].map((left) => (
            <div
              key={left}
              className="absolute top-2 h-5 w-px bg-white/[0.14]"
              style={{ left: `${left}%` }}
              aria-hidden="true"
            />
          ))}
          <div className="absolute left-1/2 top-1 h-7 w-px bg-white/25" aria-hidden="true" />

          <motion.div
            className="absolute top-0 h-10"
            style={{ x: "-50%" }}
            animate={{ left: `${track * 100}%` }}
            transition={flash ? SNAP : RECOVER}
            aria-hidden="true"
          >
            <div
              className={cn(
                "h-8 w-[2px] transition-colors duration-150",
                flash ? "bg-negative" : "bg-accent-bright",
              )}
            />
            <div
              className={cn(
                "absolute left-1/2 top-8 h-2 w-2 -translate-x-1/2 rotate-45 border-b border-r transition-colors duration-150",
                flash
                  ? "border-negative bg-negative"
                  : "border-accent-bright bg-accent-bright",
              )}
            />
          </motion.div>
        </div>

        <div className="num mt-1 flex justify-between text-2xs text-subtle" aria-hidden="true">
          <span>−{DEMO.threshold.toFixed(2)}</span>
          <span>0.00</span>
          <span>+{DEMO.threshold.toFixed(2)}</span>
        </div>

        {/* Controls */}
        <div className="mt-5 grid grid-cols-3 gap-2">
          <ShockButton onClick={() => shock(0.02, "+2% SPY")} label="Apply a plus two percent SPY shock">
            +2% SPY
          </ShockButton>
          <ShockButton onClick={() => shock(-0.03, "−3% QQQ")} label="Apply a minus three percent drop">
            −3% QQQ
          </ShockButton>
          <ShockButton onClick={reset} label="Reset the instrument" muted>
            Reset
          </ShockButton>
        </div>

        {/* Ledger */}
        <div className="mt-5 border-t border-white/[0.08] pt-3">
          <div className="num text-2xs uppercase tracking-[0.14em] text-subtle">
            Corrective orders
          </div>
          <ul className="mt-2 min-h-[3.75rem] space-y-1.5">
            <AnimatePresence initial={false}>
              {ledger.length === 0 ? (
                <li key="empty" className="text-2xs text-subtle">
                  Book is flat. Exposure drifts as the market moves.
                </li>
              ) : (
                ledger.map((line) => (
                  <motion.li
                    key={line.id}
                    layout={!reduceMotion}
                    initial={reduceMotion ? false : { opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={reduceMotion ? undefined : { opacity: 0 }}
                    transition={SNAP}
                    className="flex items-baseline justify-between text-2xs"
                  >
                    <span className="num tabular-nums">
                      <span className={line.side === "sell" ? "text-negative" : "text-positive"}>
                        {line.side.toUpperCase()}
                      </span>{" "}
                      <span className="text-foreground">{num(line.qty, 3)}</span>{" "}
                      <span className="text-subtle">{DEMO.underlying}</span>
                    </span>
                    <span className="num tabular-nums text-subtle">
                      {usd(line.notional, 0)}
                    </span>
                  </motion.li>
                ))
              )}
            </AnimatePresence>
          </ul>
        </div>
      </div>
    </div>
  );
}

function ShockButton({
  children,
  onClick,
  label,
  muted,
}: {
  children: React.ReactNode;
  onClick: () => void;
  label: string;
  muted?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        "num h-9 rounded-md border text-2xs font-medium",
        "transition-colors duration-100 active:translate-y-px",
        muted
          ? "border-white/[0.08] bg-transparent text-subtle hover:border-white/20 hover:text-foreground"
          : "border-white/[0.08] bg-surface-raised text-foreground hover:border-accent hover:bg-accent/10",
      )}
    >
      {children}
    </button>
  );
}
