"use client";

import { motion, useMotionValueEvent, useReducedMotion, useScroll, useTransform } from "framer-motion";
import { Brain, Magnet, Radar, ShieldCheck } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/format";

/**
 * The loop, told by scrolling through it.
 *
 * A tall track pins one panel and advances through four stages as you scroll.
 * This is the one place on the page where scroll position drives state rather
 * than merely triggering an entrance — appropriate here because the subject
 * *is* a sequence, and reading it as a sequence is the point.
 *
 * Under `prefers-reduced-motion` the whole mechanism is abandoned and the four
 * stages render as a plain list. A pinned, scroll-hijacked section is precisely
 * the kind of thing that makes motion-sensitive users ill, and "shorter" is not
 * an acceptable substitute for "off".
 */

const STAGES = [
  {
    icon: Radar,
    code: "01",
    title: "Scan",
    body: "Pulls live option chains for SPY, QQQ, NVDA and AAPL, solves implied volatility from the NBBO mid, and ranks each name against a year of realised movement.",
    metric: "4 underlyings · 255 daily bars",
  },
  {
    icon: Brain,
    code: "02",
    title: "Reason",
    body: "Featherless AI serves the strategy reasoner. It selects from a shortlist that already cleared every gate, so a contract it invents can never reach the broker.",
    metric: "Closed-menu schema · ~4s latency",
  },
  {
    icon: ShieldCheck,
    code: "03",
    title: "Gate",
    body: "Nine arithmetic checks run against a fresh quote at submission. No model output can widen a limit. A failed check kills the order and records which one.",
    metric: "9 deterministic gates",
  },
  {
    icon: Magnet,
    code: "04",
    title: "Hedge",
    body: "Every five seconds, exposure is recomputed per underlying and pulled back to zero with fractional equity orders sized to three decimal places.",
    metric: "5s cadence · 0.001Δ resolution",
  },
];

export function LoopScrollytelling() {
  const reduceMotion = useReducedMotion();
  const trackRef = React.useRef<HTMLDivElement>(null);
  const [active, setActive] = React.useState(0);

  const { scrollYProgress } = useScroll({
    target: trackRef,
    offset: ["start start", "end end"],
  });

  const index = useTransform(scrollYProgress, [0, 1], [0, STAGES.length]);

  useMotionValueEvent(index, "change", (value) => {
    const next = Math.min(STAGES.length - 1, Math.max(0, Math.floor(value)));
    setActive((prev) => (prev === next ? prev : next));
  });

  const progress = useTransform(scrollYProgress, [0, 1], ["0%", "100%"]);

  if (reduceMotion) {
    return (
      <ol className="grid gap-4 md:grid-cols-2">
        {STAGES.map((stage) => (
          <li key={stage.code} className="rounded-lg border border-white/[0.08] bg-surface p-6">
            <StageBody stage={stage} active />
          </li>
        ))}
      </ol>
    );
  }

  return (
    <div ref={trackRef} className="relative h-[360vh]">
      <div className="sticky top-24 flex items-center">
        <div className="w-full overflow-hidden rounded-lg border border-white/[0.08] bg-surface">
          <div className="grid md:grid-cols-[13rem_minmax(0,1fr)]">
            {/* Rail */}
            <nav
              aria-label="Loop stages"
              className="relative border-b border-white/[0.08] px-4 py-4 md:border-b-0 md:border-r md:py-6"
            >
              {/* Progress spine */}
              <div className="absolute left-0 top-0 hidden h-full w-px bg-white/[0.08] md:block">
                <motion.div
                  className="w-px bg-accent"
                  style={{ height: progress }}
                  aria-hidden="true"
                />
              </div>

              <ul className="flex gap-2 md:flex-col md:gap-1">
                {STAGES.map((stage, i) => {
                  const isActive = i === active;
                  return (
                    <li key={stage.code} className="flex-1 md:flex-none">
                      <div
                        className={cn(
                          "flex items-center gap-2 rounded-md px-2 py-2 transition-colors duration-200",
                          isActive ? "bg-white/[0.05]" : "bg-transparent",
                        )}
                      >
                        <span
                          className={cn(
                            "num text-2xs tabular-nums transition-colors duration-200",
                            isActive ? "text-accent-bright" : "text-subtle",
                          )}
                        >
                          {stage.code}
                        </span>
                        <span
                          className={cn(
                            "text-xs font-medium transition-colors duration-200",
                            isActive ? "text-foreground" : "text-subtle",
                          )}
                        >
                          {stage.title}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </nav>

            {/* Panel */}
            <div className="relative min-h-[19rem] p-6 md:p-8">
              {STAGES.map((stage, i) => (
                <motion.div
                  key={stage.code}
                  className="absolute inset-0 p-6 md:p-8"
                  initial={false}
                  animate={{
                    opacity: i === active ? 1 : 0,
                    y: i === active ? 0 : 10,
                  }}
                  transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
                  style={{ pointerEvents: i === active ? "auto" : "none" }}
                  aria-hidden={i !== active}
                >
                  <StageBody stage={stage} active={i === active} />
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StageBody({
  stage,
  active,
}: {
  stage: (typeof STAGES)[number];
  active: boolean;
}) {
  const Icon = stage.icon;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2">
        <Icon
          className={cn("h-4 w-4", active ? "text-accent-bright" : "text-subtle")}
          aria-hidden="true"
        />
        <span className="num text-2xs tabular-nums text-subtle">{stage.code}</span>
      </div>
      <h3 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">
        {stage.title}
      </h3>
      <p className="mt-3 max-w-lg text-sm leading-relaxed text-muted">{stage.body}</p>
      <div className="mt-auto pt-6">
        <span className="num text-2xs tabular-nums text-subtle">{stage.metric}</span>
      </div>
    </div>
  );
}
