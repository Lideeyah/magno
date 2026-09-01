"use client";

import { animate, useInView, useReducedMotion } from "framer-motion";
import * as React from "react";

/**
 * Counts a figure up when it first enters view.
 *
 * Written straight to the DOM node rather than through React state, so a 900ms
 * count costs zero re-renders. The easing is a strong ease-out: fast at the
 * start, settling at the end, which reads as a value arriving rather than a
 * number spinning.
 */
export function CountUp({
  to,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 0.9,
  className,
}: {
  to: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-10%" });
  const reduceMotion = useReducedMotion();

  const format = React.useCallback(
    (value: number) =>
      `${prefix}${value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}${suffix}`,
    [prefix, suffix, decimals],
  );

  React.useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (reduceMotion) {
      node.textContent = format(to);
      return;
    }
    if (!inView) return;

    const controls = animate(0, to, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (value) => {
        node.textContent = format(value);
      },
    });
    return () => controls.stop();
  }, [inView, to, duration, format, reduceMotion]);

  return (
    <span ref={ref} className={className}>
      {/* Server-rendered fallback: the final value, so the number is correct
          with JavaScript disabled and there is no layout shift on hydration. */}
      {format(reduceMotion ? to : 0)}
    </span>
  );
}
