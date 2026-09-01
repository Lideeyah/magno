"use client";

import {
  motion,
  useMotionValue,
  useMotionValueEvent,
  useReducedMotion,
  useSpring,
  useTransform,
} from "framer-motion";
import * as React from "react";

import { bookAt, deltaToTrack, DEMO } from "@/lib/demoBook";
import { cn, greek, num, usd } from "@/lib/format";

/**
 * Drag-to-scrub stress test.
 *
 * The readouts are driven from a `useMotionValue` rather than React state, so
 * scrubbing stays fluid at pointer framerate instead of queueing a re-render per
 * pixel. Every value shown is recomputed through Black-Scholes at the dragged
 * spot — this is the same `bookAt` the hero dial uses, so the two instruments
 * can never disagree.
 */

const RANGE = 0.05; // ±5%
const TRACK_PAD = 14; // half the handle width, keeps it inside the rail

export function TactileScrubber({ className }: { className?: string }) {
  const reduceMotion = useReducedMotion();
  const railRef = React.useRef<HTMLDivElement>(null);
  const [width, setWidth] = React.useState(0);

  // Fraction of the track, 0–1. 0.5 is a flat market.
  const position = useMotionValue(0.5);
  const smooth = useSpring(position, { stiffness: 400, damping: 30 });

  React.useEffect(() => {
    const node = railRef.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    observer.observe(node);
    setWidth(node.getBoundingClientRect().width);
    return () => observer.disconnect();
  }, []);

  // Mirrored into state only for the parts of the UI that genuinely need to
  // re-render (colour changes, side of the hedge). The numbers themselves are
  // written directly to the DOM below.
  const [snapshot, setSnapshot] = React.useState(() => bookAt(0));

  useMotionValueEvent(smooth, "change", (value) => {
    const move = (value - 0.5) * 2 * RANGE;
    const next = bookAt(move);
    setSnapshot((prev) =>
      // Avoid a re-render per pixel: only when something visible actually flips.
      prev.breached === next.breached && prev.hedgeSide === next.hedgeSide
        ? prev
        : next,
    );
  });

  const handleX = useTransform(smooth, (v) =>
    width ? TRACK_PAD + v * (width - TRACK_PAD * 2) : 0,
  );

  const setFromClientX = React.useCallback(
    (clientX: number) => {
      const node = railRef.current;
      if (!node) return;
      const rect = node.getBoundingClientRect();
      const raw = (clientX - rect.left - TRACK_PAD) / (rect.width - TRACK_PAD * 2);
      position.set(Math.min(1, Math.max(0, raw)));
    },
    [position],
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 0.1 : 0.02;
    if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      event.preventDefault();
      position.set(Math.max(0, position.get() - step));
    } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      event.preventDefault();
      position.set(Math.min(1, position.get() + step));
    } else if (event.key === "Home") {
      event.preventDefault();
      position.set(0);
    } else if (event.key === "End") {
      event.preventDefault();
      position.set(1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      position.set(0.5);
    }
  };

  // Live numeric readouts, written straight to the DOM so scrubbing never
  // waits on React.
  const moveRef = React.useRef<HTMLSpanElement>(null);
  const spotRef = React.useRef<HTMLDivElement>(null);
  const deltaRef = React.useRef<HTMLDivElement>(null);
  const qtyRef = React.useRef<HTMLSpanElement>(null);
  const notionalRef = React.useRef<HTMLDivElement>(null);
  const needleRef = React.useRef<HTMLDivElement>(null);

  useMotionValueEvent(smooth, "change", (value) => {
    const move = (value - 0.5) * 2 * RANGE;
    const b = bookAt(move);
    if (moveRef.current)
      moveRef.current.textContent = `${move >= 0 ? "+" : "−"}${(Math.abs(move) * 100).toFixed(2)}%`;
    if (spotRef.current) spotRef.current.textContent = num(b.spot);
    if (deltaRef.current) deltaRef.current.textContent = greek(b.netDelta);
    if (qtyRef.current)
      qtyRef.current.textContent = b.hedgeQty < 0.001 ? "—" : num(b.hedgeQty, 3);
    if (notionalRef.current)
      notionalRef.current.textContent =
        b.hedgeQty < 0.001 ? "—" : usd(b.hedgeNotional, 0);
    if (needleRef.current)
      needleRef.current.style.left = `${deltaToTrack(b.netDelta) * 100}%`;
  });

  const currentMovePct = ((position.get() - 0.5) * 2 * RANGE * 100).toFixed(2);

  return (
    <div
      className={cn(
        "rounded-lg border border-white/[0.08] bg-surface p-6",
        className,
      )}
    >
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
        {/* Scrubber */}
        <div>
          <div className="flex items-baseline justify-between">
            <span className="num text-2xs uppercase tracking-[0.14em] text-subtle">
              Underlying move
            </span>
            <span
              ref={moveRef}
              className="num text-2xl font-medium tabular-nums text-foreground"
            >
              +0.00%
            </span>
          </div>

          <div
            ref={railRef}
            className="relative mt-5 h-12 cursor-ew-resize touch-none select-none"
            onPointerDown={(event) => {
              event.currentTarget.setPointerCapture(event.pointerId);
              setFromClientX(event.clientX);
            }}
            onPointerMove={(event) => {
              if (event.buttons === 0) return;
              setFromClientX(event.clientX);
            }}
          >
            <div className="absolute inset-x-0 top-[22px] h-1 rounded-full bg-white/[0.07]" />
            <div className="absolute left-1/2 top-4 h-5 w-px bg-white/25" aria-hidden="true" />

            {/* Tick marks */}
            {[0, 0.25, 0.75, 1].map((t) => (
              <div
                key={t}
                className="absolute top-[19px] h-2 w-px bg-white/[0.12]"
                style={{ left: `calc(${TRACK_PAD}px + ${t} * (100% - ${TRACK_PAD * 2}px))` }}
                aria-hidden="true"
              />
            ))}

            <motion.div
              role="slider"
              tabIndex={0}
              aria-label="Underlying price move"
              aria-valuemin={-RANGE * 100}
              aria-valuemax={RANGE * 100}
              aria-valuenow={Number(currentMovePct)}
              aria-valuetext={`${currentMovePct} percent`}
              onKeyDown={onKeyDown}
              className={cn(
                "absolute top-2 h-7 w-7 -translate-x-1/2 rounded-full border",
                "border-white/20 bg-surface-raised shadow-lg",
                "cursor-grab active:cursor-grabbing",
                "focus-visible:outline-2 focus-visible:outline-accent-bright",
              )}
              style={{ x: handleX, left: 0 }}
              whileTap={reduceMotion ? undefined : { scale: 0.92 }}
            >
              <span className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent-bright" />
            </motion.div>
          </div>

          <div className="num flex justify-between text-2xs text-subtle">
            <span>−5.00%</span>
            <span>0.00%</span>
            <span>+5.00%</span>
          </div>

          <p className="mt-4 text-2xs leading-relaxed text-subtle">
            Drag the handle, or focus it and use the arrow keys. Every figure is
            re-priced through Black-Scholes at the shocked spot — the delta drift is
            genuine gamma on a 30-day {DEMO.underlying} call, not a scripted curve.
          </p>
        </div>

        {/* Readouts */}
        <div className="space-y-4">
          <div className="rounded-md border border-white/[0.08] bg-background p-4">
            <div className="num text-2xs uppercase tracking-[0.14em] text-subtle">
              {DEMO.underlying} spot
            </div>
            <div ref={spotRef} className="num mt-1 text-lg tabular-nums text-foreground">
              {num(DEMO.spot)}
            </div>
          </div>

          <div
            className={cn(
              "rounded-md border bg-background p-4 transition-colors duration-150",
              snapshot.breached ? "border-negative/40" : "border-white/[0.08]",
            )}
          >
            <div className="flex items-center justify-between">
              <span className="num text-2xs uppercase tracking-[0.14em] text-subtle">
                Net delta
              </span>
              <span
                className={cn(
                  "num text-2xs uppercase tracking-[0.14em]",
                  snapshot.breached ? "text-negative" : "text-positive",
                )}
              >
                {snapshot.breached ? "Breached" : "In band"}
              </span>
            </div>
            <div
              ref={deltaRef}
              className={cn(
                "num mt-1 text-lg tabular-nums transition-colors duration-150",
                snapshot.breached ? "text-negative" : "text-foreground",
              )}
            >
              {greek(0)}
            </div>

            {/* Mini track mirroring the terminal dial */}
            <div className="relative mt-3 h-4">
              <div className="absolute inset-x-0 top-[7px] h-px bg-white/[0.10]" />
              <div
                className="absolute top-[6px] h-[3px] bg-accent/40"
                style={{ left: "34%", width: "32%" }}
                aria-hidden="true"
              />
              <div ref={needleRef} className="absolute top-0 h-4" style={{ left: "50%" }}>
                <div
                  className={cn(
                    "h-4 w-[2px] -translate-x-1/2 transition-colors duration-150",
                    snapshot.breached ? "bg-negative" : "bg-accent-bright",
                  )}
                />
              </div>
            </div>
          </div>

          <div className="rounded-md border border-white/[0.08] bg-background p-4">
            <div className="num text-2xs uppercase tracking-[0.14em] text-subtle">
              Corrective hedge
            </div>
            <div className="mt-1 flex items-baseline gap-2">
              <span
                className={cn(
                  "num text-2xs uppercase",
                  snapshot.hedgeSide === "sell" ? "text-negative" : "text-positive",
                )}
              >
                {snapshot.breached ? snapshot.hedgeSide : "—"}
              </span>
              <span ref={qtyRef} className="num text-lg tabular-nums text-foreground">
                —
              </span>
              <span className="num text-2xs text-subtle">{DEMO.underlying}</span>
            </div>
            <div ref={notionalRef} className="num mt-1 text-2xs tabular-nums text-subtle">
              —
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
