"use client";

import { motion, useInView, useReducedMotion } from "framer-motion";
import * as React from "react";

import { cn } from "@/lib/format";

/**
 * The mechanics bento.
 *
 * Each card's hover state runs an animation that *demonstrates* its claim
 * rather than decorating it — a rejected spread is struck through and replaced,
 * a tilted seesaw levels itself, isolated buckets stay separate while a naive
 * total collapses to zero. If the animation didn't explain something, it
 * wouldn't be here.
 */

const SPRING = { type: "spring" as const, stiffness: 400, damping: 30 };

/**
 * A card's demonstration should not be hover-only: on touch there is no hover,
 * so the animation would simply never play. Each card therefore plays itself
 * once as it enters view, and responds to hover thereafter.
 */
function useDemoTrigger() {
  const ref = React.useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-20% 0px -20% 0px" });
  const [hovered, setHovered] = React.useState(false);
  const [played, setPlayed] = React.useState(false);

  React.useEffect(() => {
    if (!inView) return;
    setPlayed(true);
    const timer = setTimeout(() => setPlayed(false), 2200);
    return () => clearTimeout(timer);
  }, [inView]);

  return { ref, active: hovered || played, setHovered };
}

const Card = React.forwardRef<
  HTMLDivElement,
  {
    className?: string;
    children: React.ReactNode;
    onHoverChange: (hovered: boolean) => void;
  }
>(function Card({ className, children, onHoverChange }, ref) {
  return (
    <div
      ref={ref}
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-lg border border-white/[0.08] bg-surface p-6",
        "transition-colors duration-150 hover:border-white/[0.16]",
        className,
      )}
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
      onFocus={() => onHoverChange(true)}
      onBlur={() => onHoverChange(false)}
      // Keyboard users get the same demonstration as pointer users.
      tabIndex={0}
    >
      {children}
    </div>
  );
});

function Heading({ title, body }: { title: string; body: string }) {
  return (
    <>
      <h3 className="text-base font-medium tracking-tight text-foreground">{title}</h3>
      <p className="mt-2 text-xs leading-relaxed text-muted">{body}</p>
    </>
  );
}

/* -------------------------------------------------------------------------- */
/* 1. Liquidity gate — wide                                                   */
/* -------------------------------------------------------------------------- */
function LiquidityGate() {
  const reduceMotion = useReducedMotion();
  const { ref, active, setHovered } = useDemoTrigger();

  return (
    <Card ref={ref} className="lg:col-span-2" onHoverChange={setHovered}>
      <Heading
        title="Screen out toxic pricing."
        body="Most bots buy into illiquid options and give up 5–15% the moment they enter. Magno rejects any contract whose bid/ask spread exceeds 5% of the mid price — before the order is ever constructed."
      />

      <div className="mt-6 rounded-md border border-white/[0.08] bg-background p-4">
        <div className="num mb-3 flex items-center justify-between text-2xs uppercase tracking-[0.14em] text-subtle">
          <span>Contract</span>
          <span>Spread</span>
        </div>

        <div className="space-y-2">
          {/* Rejected row */}
          <div className="relative flex items-center justify-between">
            <span className="num text-2xs text-muted">SPY 770C · 30d</span>
            <div className="relative">
              <span
                className={cn(
                  "num text-sm transition-colors duration-200",
                  active ? "text-negative/50" : "text-foreground",
                )}
              >
                7.20%
              </span>
              {/* Strike-through drawn as a path so it reads as an action */}
              <svg
                className="pointer-events-none absolute inset-0 h-full w-full overflow-visible"
                aria-hidden="true"
              >
                <motion.line
                  x1="-4"
                  y1="50%"
                  x2="calc(100% + 4px)"
                  y2="50%"
                  stroke="var(--negative)"
                  strokeWidth="1.5"
                  initial={false}
                  animate={{ pathLength: active ? 1 : 0 }}
                  transition={reduceMotion ? { duration: 0 } : { duration: 0.22, ease: [0, 0, 0.2, 1] }}
                  style={{ pathLength: 0 }}
                />
              </svg>
            </div>
          </div>

          {/* Accepted row, revealed on hover */}
          <motion.div
            className="flex items-center justify-between"
            initial={false}
            animate={{
              opacity: active ? 1 : 0.25,
              y: active ? 0 : 4,
            }}
            transition={reduceMotion ? { duration: 0 } : SPRING}
          >
            <span className="num text-2xs text-muted">SPY 765C · 30d</span>
            <span
              className={cn(
                "num text-sm transition-colors duration-200",
                active ? "text-positive" : "text-subtle",
              )}
            >
              2.10%
            </span>
          </motion.div>
        </div>

        <div className="mt-3 border-t border-white/[0.08] pt-2">
          <motion.p
            className="num text-2xs"
            initial={false}
            animate={{ opacity: active ? 1 : 0 }}
            transition={reduceMotion ? { duration: 0 } : { duration: 0.15 }}
          >
            <span className="text-negative">SPREAD_TOO_WIDE</span>
            <span className="text-subtle"> → rerouted to the tightest book</span>
          </motion.p>
        </div>
      </div>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* 2. Rebalancing — tall                                                      */
/* -------------------------------------------------------------------------- */
function DynamicHedging() {
  const reduceMotion = useReducedMotion();
  const { ref, active: hovered, setHovered } = useDemoTrigger();

  return (
    <Card ref={ref} className="lg:row-span-2" onHoverChange={setHovered}>
      <Heading
        title="Dynamic delta hedging."
        body="When a market swing pushes the book into directional risk, Magno submits fractional stock orders on Alpaca to snap exposure back to zero — every five seconds, without waiting on the model."
      />

      {/* Seesaw: tilted at rest, levels itself when hovered */}
      <div className="mt-8 flex flex-1 items-center justify-center">
        <div className="relative w-full max-w-[15rem]">
          <svg viewBox="0 0 240 120" className="w-full" aria-hidden="true">
            {/* Fulcrum */}
            <path d="M120 74 L133 100 L107 100 Z" fill="var(--border-strong)" />
            <line
              x1="20"
              y1="104"
              x2="220"
              y2="104"
              stroke="var(--border)"
              strokeWidth="1"
            />

            <motion.g
              initial={false}
              animate={{ rotate: hovered ? 0 : -11 }}
              transition={
                reduceMotion
                  ? { duration: 0 }
                  : { type: "spring", stiffness: 220, damping: 14 }
              }
              style={{ originX: "120px", originY: "72px" }}
            >
              {/* Beam */}
              <rect
                x="26"
                y="68"
                width="188"
                height="5"
                rx="2.5"
                fill={hovered ? "var(--accent-bright)" : "var(--border-strong)"}
              />
              {/* Option leg */}
              <circle cx="52" cy="58" r="9" fill="var(--surface-raised)" stroke="var(--border-strong)" />
              <text
                x="52"
                y="62"
                textAnchor="middle"
                className="num"
                fontSize="9"
                fill="var(--muted)"
              >
                Δ
              </text>
              {/* Equity hedge leg */}
              <circle
                cx="188"
                cy="58"
                r="9"
                fill="var(--surface-raised)"
                stroke={hovered ? "var(--accent-bright)" : "var(--border-strong)"}
              />
              <text
                x="188"
                y="62"
                textAnchor="middle"
                className="num"
                fontSize="8"
                fill={hovered ? "var(--accent-bright)" : "var(--muted)"}
              >
                SH
              </text>
            </motion.g>
          </svg>

          <div className="num mt-3 flex items-center justify-between text-2xs">
            <span className="text-subtle">Net Δ</span>
            <motion.span
              initial={false}
              animate={{ opacity: 1 }}
              className={hovered ? "text-positive" : "text-negative"}
            >
              {hovered ? "0.000" : "+21.04"}
            </motion.span>
          </div>
        </div>
      </div>

      <p className="mt-6 border-t border-white/[0.08] pt-3 text-2xs leading-relaxed text-subtle">
        Sized to three decimal places. Rounding to whole shares would strand up to
        half a delta per name — most of the trigger threshold on a four-name book.
      </p>
    </Card>
  );
}

/* -------------------------------------------------------------------------- */
/* 3. Isolated buckets — square                                               */
/* -------------------------------------------------------------------------- */
function IsolatedBuckets() {
  const reduceMotion = useReducedMotion();
  const { ref, active: hovered, setHovered } = useDemoTrigger();

  return (
    <Card ref={ref} onHoverChange={setHovered}>
      <Heading
        title="Zero cross-asset contagion."
        body="Naive systems net total portfolio delta to zero and quietly hide two opposing directional bets inside it. Magno buckets Greeks strictly per underlying."
      />

      <div className="mt-6 space-y-2">
        {[
          { name: "SPY", delta: "+60.0", tone: "text-positive" },
          { name: "QQQ", delta: "−60.0", tone: "text-negative" },
        ].map((row) => (
          <div
            key={row.name}
            className="flex items-center justify-between rounded-md border border-white/[0.08] bg-background px-3 py-2"
          >
            <span className="num text-2xs text-muted">{row.name}</span>
            <span className={cn("num text-xs", row.tone)}>{row.delta}</span>
          </div>
        ))}

        <motion.div
          className="rounded-md border border-dashed border-white/[0.10] px-3 py-2"
          initial={false}
          animate={{ opacity: hovered ? 1 : 0.4 }}
          transition={reduceMotion ? { duration: 0 } : { duration: 0.15 }}
        >
          <div className="flex items-center justify-between">
            <span className="num text-2xs text-subtle">Naive portfolio total</span>
            <span className="num text-xs text-subtle">0.00</span>
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-negative">
            Reads neutral. Is actually a live SPY/QQQ basis bet.
          </p>
        </motion.div>
      </div>
    </Card>
  );
}

export function BentoMechanics() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <LiquidityGate />
      <DynamicHedging />
      <IsolatedBuckets />
    </div>
  );
}
