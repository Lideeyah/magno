"use client";

import * as React from "react";

import { cn } from "@/lib/format";

/**
 * Flashes a value briefly in the direction it moved, then settles back to
 * neutral. The colour is transient on purpose: a number left permanently green
 * because it once ticked up is misinformation.
 */
export function FlashValue({
  value,
  format,
  className,
  restingClassName,
  /** Sub-threshold changes are ignored so noise doesn't cause constant flicker. */
  epsilon = 1e-9,
}: {
  value: number;
  format: (v: number) => string;
  className?: string;
  restingClassName?: string;
  epsilon?: number;
}) {
  const previous = React.useRef(value);
  const [direction, setDirection] = React.useState<"up" | "down" | null>(null);

  React.useEffect(() => {
    const delta = value - previous.current;
    previous.current = value;
    if (Math.abs(delta) <= epsilon) return;

    setDirection(delta > 0 ? "up" : "down");
    const timer = setTimeout(() => setDirection(null), 320);
    return () => clearTimeout(timer);
  }, [value, epsilon]);

  return (
    <span
      className={cn(
        "num transition-colors duration-300 ease-exit",
        direction === "up" && "text-positive",
        direction === "down" && "text-negative",
        direction === null && restingClassName,
        className,
      )}
    >
      {format(value)}
    </span>
  );
}
