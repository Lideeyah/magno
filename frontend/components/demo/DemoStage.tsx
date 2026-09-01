"use client";

import { motion, useReducedMotion } from "framer-motion";
import * as React from "react";

import { cn } from "@/lib/format";

import { STAGES, type Stage, formatClock } from "./sequence";

/**
 * Chrome for the automated run: progress rail, stage list, narration.
 *
 * Everything reads its position from the single `elapsed` value, so the bar,
 * the highlighted stage and the narration can never disagree about where the
 * run is.
 */
export function DemoChrome({
  elapsed,
  total,
  stage,
  running,
  live,
}: {
  elapsed: number;
  total: number;
  stage: Stage;
  running: boolean;
  live: boolean;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-white/[0.08] bg-background/90 backdrop-blur-md">
      {/* Progress rail — the only always-moving element on screen. */}
      <div className="h-0.5 w-full bg-white/[0.06]">
        <div
          className="h-full bg-accent transition-[width] duration-300 ease-linear"
          style={{ width: `${(elapsed / total) * 100}%` }}
        />
      </div>

      <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-x-6 gap-y-2 px-6 py-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full",
              live ? "bg-positive" : "bg-subtle",
            )}
            aria-hidden="true"
          />
          <span className="num text-2xs uppercase tracking-[0.14em] text-subtle">
            {live ? "Live Alpaca paper" : "Connecting"}
          </span>
        </div>

        <ol className="flex flex-wrap items-center gap-1">
          {STAGES.map((s) => {
            const done = elapsed >= s.start + s.duration;
            const active = s.id === stage.id;
            return (
              <li key={s.id}>
                <span
                  className={cn(
                    "num flex items-center gap-1.5 rounded-md px-2 py-1 text-2xs transition-colors duration-300",
                    active
                      ? "bg-accent/15 text-accent-bright"
                      : done
                        ? "text-muted"
                        : "text-subtle",
                  )}
                >
                  <span className="tabular-nums">{s.index}</span>
                  <span className="hidden sm:inline">{s.label}</span>
                </span>
              </li>
            );
          })}
        </ol>

        <div className="ml-auto flex items-center gap-4">
          <span className="num text-2xs tabular-nums text-subtle">
            {formatClock(elapsed)} / {formatClock(total)}
          </span>
          {!running && (
            <span className="num text-2xs uppercase tracking-[0.14em] text-warning">
              Paused
            </span>
          )}
        </div>
      </div>

      {/* Narration for the active stage. */}
      <div className="border-t border-white/[0.06] bg-surface/40">
        <div className="mx-auto max-w-[1600px] px-6 py-3">
          <motion.div
            key={stage.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <h2 className="text-sm font-medium text-foreground">{stage.headline}</h2>
            <p className="mt-1 max-w-4xl text-xs leading-relaxed text-muted">
              {stage.narration}
            </p>
          </motion.div>
        </div>
      </div>
    </header>
  );
}

/**
 * Wraps a panel and spotlights it while its stage is active.
 *
 * Dimming rather than hiding: the surrounding book stays visible, so a viewer
 * can see that the highlighted number belongs to a real, whole terminal rather
 * than a slide.
 */
export function Spotlight({
  active,
  children,
  className,
}: {
  active: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      className={cn("relative rounded-lg", className)}
      initial={false}
      animate={{
        opacity: active ? 1 : 0.28,
        scale: active && !reduceMotion ? 1 : 0.995,
      }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
    >
      {active && (
        <motion.div
          layoutId="demo-spotlight"
          className="pointer-events-none absolute -inset-px rounded-lg ring-1 ring-accent/50"
          transition={{ type: "spring", stiffness: 260, damping: 30 }}
          aria-hidden="true"
        />
      )}
      {children}
    </motion.div>
  );
}
