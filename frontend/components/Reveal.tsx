"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import * as React from "react";

/**
 * Scroll-choreography primitives.
 *
 * Content enters as it arrives rather than being present-on-load, which is what
 * gives a long page a sense of pace. Three rules keep it from becoming the
 * sliding-content-everywhere cliché:
 *
 *  - `once: true`. An entrance that replays on every scroll-by is a speed bump.
 *  - Small distances (12px, not 60px). The eye should register arrival, not
 *    travel. Large translations read as decoration and hurt reading.
 *  - Everything collapses to "already there" under `prefers-reduced-motion` —
 *    instant, not merely faster.
 */

const EASE = [0.22, 1, 0.36, 1] as const;
const VIEWPORT = { once: true, margin: "-12% 0px -8% 0px" } as const;

export function Reveal({
  children,
  delay = 0,
  y = 12,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  y?: number;
  className?: string;
}) {
  const reduceMotion = useReducedMotion();

  if (reduceMotion) return <div className={className}>{children}</div>;

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={VIEWPORT}
      transition={{ duration: 0.45, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

const containerVariants: Variants = {
  hidden: {},
  shown: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

/** Staggers its direct `RevealItem` children as the group enters view. */
export function RevealGroup({
  children,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "ul" | "ol" | "dl";
}) {
  const reduceMotion = useReducedMotion();
  const Motion = motion[Tag];

  if (reduceMotion) return <Tag className={className}>{children}</Tag>;

  return (
    <Motion
      className={className}
      variants={containerVariants}
      initial="hidden"
      whileInView="shown"
      viewport={VIEWPORT}
    >
      {children}
    </Motion>
  );
}

export function RevealItem({
  children,
  className,
  as: Tag = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "li" | "tr";
}) {
  const reduceMotion = useReducedMotion();
  const Motion = motion[Tag];

  if (reduceMotion) return <Tag className={className}>{children}</Tag>;

  return (
    <Motion className={className} variants={itemVariants}>
      {children}
    </Motion>
  );
}

/**
 * A hairline that draws itself outward from the left as it enters view.
 * Structural rather than decorative: it marks a section boundary, and drawing
 * it makes the boundary feel authored instead of merely present.
 */
export function DrawRule({ className }: { className?: string }) {
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return <div className={className} style={{ height: 1, background: "var(--border)" }} />;
  }

  return (
    <motion.div
      className={className}
      style={{ height: 1, background: "var(--border)", transformOrigin: "left" }}
      initial={{ scaleX: 0 }}
      whileInView={{ scaleX: 1 }}
      viewport={VIEWPORT}
      transition={{ duration: 0.7, ease: EASE }}
      aria-hidden="true"
    />
  );
}
