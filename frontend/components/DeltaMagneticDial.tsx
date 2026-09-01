"use client";

import { Magnet, TrendingDown, TrendingUp } from "lucide-react";
import * as React from "react";

import { cn, greek, usd, usdCompact } from "@/lib/format";
import type { PortfolioGreeks } from "@/lib/types";

import { Badge, StatusPip } from "./ui";

/**
 * The magnetic delta dial.
 *
 * Portfolio delta is pinned to zero by the hedge engine, so the interesting
 * information is not the magnitude but the *distance from equilibrium*. The
 * scale is therefore piecewise: the drift band (±threshold) is given a
 * generous linear slice at the centre where precision matters, and everything
 * beyond it is compressed logarithmically so a runaway 200-delta position is
 * still on screen instead of pinned uselessly to the edge.
 */

const NEUTRAL_HALF_WIDTH = 0.18; // fraction of track occupied by ±1 threshold
const OUTER_HALF_WIDTH = 0.3; // remaining fraction available beyond the band
const COMPRESSION_CEILING = 50; // |Δ|/threshold that reaches the track edge

export function deltaToPosition(netDelta: number, threshold: number): number {
  if (!threshold || !Number.isFinite(netDelta)) return 0.5;
  const t = netDelta / threshold;
  const sign = Math.sign(t);
  const magnitude = Math.abs(t);

  if (magnitude <= 1) return 0.5 + t * NEUTRAL_HALF_WIDTH;

  const compressed =
    Math.log10(Math.min(magnitude, COMPRESSION_CEILING)) / Math.log10(COMPRESSION_CEILING);
  return 0.5 + sign * (NEUTRAL_HALF_WIDTH + compressed * OUTER_HALF_WIDTH);
}

export function DeltaMagneticDial({
  netDelta,
  threshold,
  deltaNotional,
  byUnderlying,
  shocked,
  className,
}: {
  netDelta: number;
  threshold: number;
  deltaNotional: number;
  byUnderlying: PortfolioGreeks["by_underlying"];
  shocked: boolean;
  className?: string;
}) {
  const breach = Math.abs(netDelta) >= threshold;
  const position = deltaToPosition(netDelta, threshold);
  const utilisation = threshold ? Math.min(Math.abs(netDelta) / threshold, 1) : 0;

  const names = Object.values(byUnderlying).sort(
    (a, b) => Math.abs(b.net_delta) - Math.abs(a.net_delta),
  );

  return (
    <div
      className={cn(
        "panel relative overflow-hidden px-4 py-4 transition-colors duration-200 ease-move",
        breach && "border-accent-bright/50",
        className,
      )}
    >
      {/* Cobalt wash while the hedge engine is engaged. Opacity only — no layout cost. */}
      <div
        className={cn(
          "pointer-events-none absolute inset-0 bg-gradient-to-r from-accent/0 via-accent/10 to-accent/0",
          "transition-opacity duration-200 ease-move",
          breach ? "opacity-100" : "opacity-0",
        )}
        aria-hidden="true"
      />

      <div className="relative flex items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <Magnet
            className={cn(
              "h-4 w-4 transition-colors duration-200 ease-move",
              breach ? "text-accent-bright" : "text-subtle",
            )}
            aria-hidden="true"
          />
          <div>
            <h2 className="text-xs font-medium uppercase tracking-[0.08em] text-muted">
              Delta equilibrium
            </h2>
            <p className="mt-0.5 text-2xs text-subtle">
              Drift cap ±{threshold.toFixed(2)}Δ · hedged with fractional equity
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {shocked && <Badge tone="warning">Shock active</Badge>}
          {breach ? (
            <Badge tone="accent" className="animate-fade-up">
              <StatusPip tone="accent" pulse />
              Hedging
            </Badge>
          ) : (
            <Badge tone="positive">
              <StatusPip tone="positive" />
              Neutral
            </Badge>
          )}
        </div>
      </div>

      {/* Headline reading */}
      <div className="relative mt-4 flex items-baseline gap-3">
        <span
          className={cn(
            "num text-3xl font-medium tabular-nums transition-colors duration-200 ease-move",
            breach ? "text-accent-bright" : "text-foreground",
          )}
        >
          {greek(netDelta)}
        </span>
        <span className="text-xs text-muted">
          net Δ ·{" "}
          <span className="num text-muted">{usdCompact(deltaNotional)}</span> notional
        </span>
      </div>

      {/* Track */}
      <div className="relative mt-4">
        <div
          className="relative h-12 select-none"
          role="meter"
          aria-valuenow={Number(netDelta.toFixed(3))}
          aria-valuemin={-threshold * COMPRESSION_CEILING}
          aria-valuemax={threshold * COMPRESSION_CEILING}
          aria-label={`Net portfolio delta ${netDelta.toFixed(3)}, drift cap plus or minus ${threshold}`}
        >
          {/* Base rail */}
          <div className="absolute inset-x-0 top-5 h-2 rounded-full bg-surface-raised ring-1 ring-inset ring-border" />

          {/* Neutral band: the region inside the drift cap */}
          <div
            className={cn(
              "absolute top-5 h-2 rounded-full transition-colors duration-200 ease-move",
              breach ? "bg-accent-dim/40" : "bg-positive/20",
            )}
            style={{
              left: `${(0.5 - NEUTRAL_HALF_WIDTH) * 100}%`,
              width: `${NEUTRAL_HALF_WIDTH * 2 * 100}%`,
            }}
            aria-hidden="true"
          />

          {/* Fill from centre to the needle */}
          <div
            className={cn(
              "absolute top-5 h-2 transition-colors duration-200 ease-move",
              breach ? "bg-accent-bright" : "bg-positive/70",
              position >= 0.5 ? "rounded-r-full" : "rounded-l-full",
            )}
            style={{
              left: `${Math.min(position, 0.5) * 100}%`,
              width: `${Math.abs(position - 0.5) * 100}%`,
            }}
            aria-hidden="true"
          />

          {/* Threshold posts */}
          {[-1, 1].map((side) => (
            <div
              key={side}
              className="absolute top-3 h-6 w-px bg-border-strong"
              style={{ left: `${(0.5 + side * NEUTRAL_HALF_WIDTH) * 100}%` }}
              aria-hidden="true"
            />
          ))}

          {/* Zero anchor */}
          <div
            className="absolute top-2 h-8 w-px bg-subtle"
            style={{ left: "50%" }}
            aria-hidden="true"
          />

          {/* Needle. Positioned with transform so movement is composited. */}
          <div
            className="absolute top-0 h-12 w-0 transition-transform duration-300 ease-move will-change-transform"
            style={{ left: `${position * 100}%`, transform: "translateX(-50%)" }}
            aria-hidden="true"
          >
            <div
              className={cn(
                "mx-auto h-12 w-0.5 rounded-full transition-colors duration-200 ease-move",
                breach ? "bg-accent-bright" : "bg-foreground",
              )}
            />
            <div
              className={cn(
                "absolute left-1/2 top-4 h-4 w-4 -translate-x-1/2 rounded-full border-2",
                "transition-colors duration-200 ease-move",
                breach
                  ? "border-accent-bright bg-background"
                  : "border-foreground bg-background",
              )}
              style={
                breach
                  ? { animation: "pulse-ring 1.8s cubic-bezier(0,0,0.2,1) infinite" }
                  : undefined
              }
            />
          </div>
        </div>

        <div className="mt-1 flex items-center justify-between text-2xs text-subtle">
          <span className="num flex items-center gap-1">
            <TrendingDown className="h-3 w-3" aria-hidden="true" />
            short
          </span>
          <span className="num">−{threshold.toFixed(2)}</span>
          <span className="num text-muted">0.000</span>
          <span className="num">+{threshold.toFixed(2)}</span>
          <span className="num flex items-center gap-1">
            long
            <TrendingUp className="h-3 w-3" aria-hidden="true" />
          </span>
        </div>
      </div>

      {/* Per-underlying breakdown: hedges execute per name, so the operator
          needs to see which name actually breached. */}
      <div className="relative mt-4 border-t border-border pt-3">
        {names.length === 0 ? (
          <p className="text-2xs text-subtle">
            No exposure. The dial activates once the agent opens its first position.
          </p>
        ) : (
          <>
            <div className="th mb-2">Exposure by underlying</div>
            <ul className="space-y-1.5">
              {names.map((exposure) => {
                const nameBreach = Math.abs(exposure.net_delta) >= threshold;
                const fill = Math.min(
                  Math.abs(exposure.net_delta) / Math.max(threshold * 5, 1),
                  1,
                );
                return (
                  <li key={exposure.underlying} className="flex items-center gap-3">
                    <span className="num w-12 shrink-0 text-2xs text-muted">
                      {exposure.underlying}
                    </span>
                    <div className="relative h-1 flex-1 overflow-hidden rounded-full bg-surface-raised">
                      <div
                        className={cn(
                          "absolute top-0 h-full transition-[width,background-color] duration-200 ease-move",
                          nameBreach ? "bg-accent-bright" : "bg-subtle",
                        )}
                        style={{
                          width: `${(fill / 2) * 100}%`,
                          left: exposure.net_delta >= 0 ? "50%" : undefined,
                          right: exposure.net_delta < 0 ? "50%" : undefined,
                        }}
                      />
                      <div className="absolute left-1/2 top-0 h-full w-px bg-border-strong" />
                    </div>
                    <span
                      className={cn(
                        "num w-16 shrink-0 text-right text-2xs",
                        nameBreach ? "text-accent-bright" : "text-muted",
                      )}
                    >
                      {greek(exposure.net_delta)}
                    </span>
                    <span className="num hidden w-20 shrink-0 text-right text-2xs text-subtle sm:block">
                      {usd(exposure.delta_notional, 0)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {/* Utilisation read-out doubles as the "how close are we" signal */}
      <div className="relative mt-3 flex items-center justify-between text-2xs">
        <span className="text-subtle">Drift-cap utilisation</span>
        <span className={cn("num", breach ? "text-accent-bright" : "text-muted")}>
          {(utilisation * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}
