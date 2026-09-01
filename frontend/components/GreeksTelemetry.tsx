"use client";

import { Activity, Clock3, Gauge, Layers, Waves } from "lucide-react";
import * as React from "react";

import { cn, greek, num, pct, usd, usdSigned } from "@/lib/format";
import type { PortfolioGreeks, VolProfile } from "@/lib/types";

import { Badge, EmptyState, Panel, Skeleton } from "./ui";

/**
 * High-density Greeks readout.
 *
 * Every figure states what a 1-unit move in its risk factor is worth in
 * dollars, because "gamma 0.0421" is meaningless to read at a glance and
 * "+$4.21 of delta per $1 move" is not.
 */

function GreekCard({
  icon: Icon,
  symbol,
  name,
  value,
  interpretation,
  tone = "neutral",
}: {
  icon: React.ComponentType<{ className?: string }>;
  symbol: string;
  name: string;
  value: string;
  interpretation: string;
  tone?: "neutral" | "positive" | "negative" | "accent";
}) {
  const toneClass = {
    neutral: "text-foreground",
    positive: "text-positive",
    negative: "text-negative",
    accent: "text-accent-bright",
  }[tone];

  return (
    <div className="flex min-w-0 flex-col gap-1 border-border px-4 py-3">
      <div className="flex items-center gap-1.5">
        <Icon className="h-3 w-3 text-subtle" aria-hidden="true" />
        <span className="th">
          {symbol} <span className="normal-case tracking-normal">{name}</span>
        </span>
      </div>
      <div className={cn("num truncate text-lg font-medium", toneClass)}>{value}</div>
      <div className="truncate text-2xs leading-relaxed text-subtle">{interpretation}</div>
    </div>
  );
}

export function GreeksTelemetry({
  greeks,
  volSurface,
  loading,
  className,
}: {
  greeks: PortfolioGreeks | null;
  volSurface: VolProfile[];
  loading: boolean;
  className?: string;
}) {
  if (loading && !greeks) {
    return (
      <Panel title="Portfolio Greeks" className={className}>
        <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="space-y-2 bg-surface px-4 py-3">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-3 w-28" />
            </div>
          ))}
        </div>
      </Panel>
    );
  }

  if (!greeks || greeks.gross_option_positions === 0) {
    return (
      <Panel title="Portfolio Greeks" className={className}>
        <EmptyState
          icon={Gauge}
          title="No option exposure yet"
          description="Greeks populate as soon as the agent opens its first contract. Engage the autopilot, or open a position from the chain below."
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Portfolio Greeks"
      subtitle="Share-equivalent exposure across the whole book"
      className={className}
      action={
        <Badge tone="neutral">
          <Layers className="h-3 w-3" aria-hidden="true" />
          {greeks.gross_option_positions} option
          {greeks.gross_option_positions === 1 ? "" : "s"}
        </Badge>
      }
    >
      <div className="grid grid-cols-2 gap-px bg-border lg:grid-cols-4">
        <div className="bg-surface">
          <GreekCard
            icon={Activity}
            symbol="Δ"
            name="Delta"
            value={greek(greeks.net_delta)}
            interpretation={`${usd(greeks.delta_notional, 0)} directional notional`}
            tone={Math.abs(greeks.net_delta) >= 1 ? "accent" : "neutral"}
          />
        </div>
        <div className="bg-surface">
          <GreekCard
            icon={Gauge}
            symbol="Γ"
            name="Gamma"
            value={num(greeks.net_gamma, 4)}
            interpretation={`Δ moves ${greek(greeks.net_gamma)} per $1 of underlying`}
          />
        </div>
        <div className="bg-surface">
          <GreekCard
            icon={Clock3}
            symbol="Θ"
            name="Theta"
            value={usdSigned(greeks.net_theta)}
            interpretation="Decay per calendar day"
            tone={greeks.net_theta >= 0 ? "positive" : "negative"}
          />
        </div>
        <div className="bg-surface">
          <GreekCard
            icon={Waves}
            symbol="ν"
            name="Vega"
            value={usdSigned(greeks.net_vega)}
            interpretation="P&L per 1 vol point"
            tone={greeks.net_vega >= 0 ? "positive" : "negative"}
          />
        </div>
      </div>

      {volSurface.length > 0 && (
        <div className="border-t border-border">
          <div className="flex items-center justify-between px-4 pt-3">
            <span className="th">Volatility surface</span>
            <span
              className="text-2xs text-subtle"
              title="Alpaca publishes no historical implied-vol series, so IV rank is the percentile of current ATM IV against the trailing one-year distribution of 20-day realised volatility."
            >
              IV rank = ATM IV percentile vs 1y realised
            </span>
          </div>
          <ul className="divide-y divide-border">
            {volSurface.map((profile) => {
              const rank = profile.iv_rank;
              const rich = rank !== null && rank >= 65;
              const cheap = rank !== null && rank <= 35;
              return (
                <li
                  key={profile.underlying}
                  className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-3 px-4 py-2"
                >
                  <span className="num text-xs text-foreground">{profile.underlying}</span>

                  <div className="flex min-w-0 items-center gap-3">
                    <div className="relative h-1 w-full max-w-[10rem] overflow-hidden rounded-full bg-surface-raised">
                      <div
                        className={cn(
                          "h-full transition-[width] duration-200 ease-move",
                          rich ? "bg-warning" : cheap ? "bg-accent-bright" : "bg-subtle",
                        )}
                        style={{ width: `${rank ?? 0}%` }}
                      />
                    </div>
                    <span className="num shrink-0 text-2xs text-muted">
                      {rank === null ? "—" : `${rank.toFixed(0)}/100`}
                    </span>
                    {rich && <Badge tone="warning">Rich</Badge>}
                    {cheap && <Badge tone="accent">Cheap</Badge>}
                  </div>

                  <div className="flex items-center gap-3 text-2xs">
                    <span className="num text-muted" title="At-the-money implied volatility">
                      IV {pct(profile.atm_iv, 1)}
                    </span>
                    <span className="num text-subtle" title="20-day realised volatility">
                      RV {pct(profile.realized_vol_20d, 1)}
                    </span>
                    <span
                      className={cn(
                        "num hidden w-16 text-right sm:block",
                        (profile.iv_premium ?? 0) > 0 ? "text-warning" : "text-accent-bright",
                      )}
                      title="Implied minus realised volatility. Positive means options are pricing more movement than has occurred."
                    >
                      {profile.iv_premium === null
                        ? "—"
                        : `${profile.iv_premium > 0 ? "+" : "−"}${pct(Math.abs(profile.iv_premium), 1)}`}
                    </span>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Panel>
  );
}
