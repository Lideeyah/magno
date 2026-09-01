"use client";

import { motion, useReducedMotion } from "framer-motion";

import { cn } from "@/lib/format";

/**
 * Staggered mask reveal for the hero headline.
 *
 * Each line sits inside an `overflow-hidden` wrapper and rises from beneath its
 * own baseline, so the text is *uncovered* rather than faded — the type never
 * renders at partial opacity, which is what makes a fade read as cheap.
 *
 * Runs once on load and never again: an entrance animation that replays is a
 * speed bump. Under `prefers-reduced-motion` the text is simply present, with
 * no transform at all.
 */

const LINE_DURATION = 0.5;
const STAGGER = 0.08;

export function RevealHeadline({
  lines,
  className,
}: {
  lines: string[];
  className?: string;
}) {
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return (
      <h1 className={className}>
        {lines.map((line, i) => (
          <span key={line} className="block">
            {line}
            {i < lines.length - 1 && <br className="hidden" />}
          </span>
        ))}
      </h1>
    );
  }

  return (
    <h1 className={className}>
      {lines.map((line, index) => (
        <span key={line} className={cn("block overflow-hidden", "pb-[0.08em]")}>
          <motion.span
            className="block"
            initial={{ y: "110%" }}
            animate={{ y: "0%" }}
            transition={{
              duration: LINE_DURATION,
              delay: index * STAGGER,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            {line}
          </motion.span>
        </span>
      ))}
    </h1>
  );
}
