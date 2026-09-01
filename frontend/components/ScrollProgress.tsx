"use client";

import { motion, useReducedMotion, useScroll, useSpring } from "framer-motion";

/**
 * Reading-progress hairline under the fixed header.
 *
 * Functional rather than decorative — on a long page it tells you how much is
 * left, which is the one thing a scrollbar does badly inside a full-bleed dark
 * layout. Springs so it glides rather than tracking the wheel jitter exactly.
 */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const reduceMotion = useReducedMotion();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 260,
    damping: 40,
    restDelta: 0.001,
  });

  return (
    <motion.div
      aria-hidden="true"
      className="h-px origin-left bg-accent"
      style={{ scaleX: reduceMotion ? scrollYProgress : scaleX }}
    />
  );
}
