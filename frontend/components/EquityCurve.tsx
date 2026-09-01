"use client";

import * as React from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { cn, greek, usd, usdSigned } from "@/lib/format";

import { EmptyState, Panel } from "./ui";

export interface CurveSample {
  t: number;
  equity: number;
  netDelta: number;
}

/**
 * Session-scoped equity and delta history.
 *
 * Samples are collected client-side from the telemetry stream, so the window is
 * "since this tab connected" rather than a full account history — labelled as
 * such, because a chart implying more history than it has is a lie about
 * performance.
 */
function EquityCurveImpl({
  samples,
  baseline,
  threshold,
  className,
}: {
  samples: CurveSample[];
  baseline: number;
  threshold: number;
  className?: string;
}) {
  const latest = samples.at(-1);
  const change = latest ? latest.equity - baseline : 0;
  const positive = change >= 0;

  const domain = React.useMemo<[number, number]>(() => {
    if (samples.length === 0) return [baseline * 0.999, baseline * 1.001];
    const values = samples.map((s) => s.equity).concat(baseline);
    const min = Math.min(...values);
    const max = Math.max(...values);
    // Guarantee a visible band even when equity is perfectly flat.
    const pad = Math.max((max - min) * 0.25, Math.max(baseline * 0.0002, 1));
    return [min - pad, max + pad];
  }, [samples, baseline]);

  const deltaDomain = React.useMemo<[number, number]>(() => {
    const peak = Math.max(
      threshold * 1.6,
      ...samples.map((s) => Math.abs(s.netDelta) * 1.2),
      1,
    );
    return [-peak, peak];
  }, [samples, threshold]);

  const timeLabel = (value: number) =>
    new Date(value).toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <Panel
      title="Session performance"
      subtitle="Sampled since this terminal connected"
      className={className}
      action={
        latest ? (
          <div className="flex items-baseline gap-2">
            <span className="num text-sm text-foreground">{usd(latest.equity)}</span>
            <span
              className={cn("num text-2xs", positive ? "text-positive" : "text-negative")}
            >
              {usdSigned(change)}
            </span>
          </div>
        ) : undefined
      }
    >
      {samples.length < 2 ? (
        <EmptyState
          title="Collecting samples"
          description="The curve draws once the telemetry stream has delivered a few frames. This takes a couple of seconds."
        />
      ) : (
        <div className="space-y-1 px-2 pb-3 pt-2">
          <div className="h-32">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={samples} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
                    <stop
                      offset="0%"
                      stopColor={positive ? "var(--positive)" : "var(--negative)"}
                      stopOpacity={0.22}
                    />
                    <stop
                      offset="100%"
                      stopColor={positive ? "var(--positive)" : "var(--negative)"}
                      stopOpacity={0}
                    />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  tickFormatter={timeLabel}
                  stroke="var(--subtle)"
                  tick={{ fontSize: 10, fill: "var(--subtle)" }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={44}
                />
                <YAxis
                  domain={domain}
                  stroke="var(--subtle)"
                  tick={{ fontSize: 10, fill: "var(--subtle)" }}
                  tickLine={false}
                  axisLine={false}
                  width={62}
                  tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`}
                />
                <ReferenceLine
                  y={baseline}
                  stroke="var(--subtle)"
                  strokeDasharray="3 3"
                  label={{
                    value: "open",
                    position: "insideTopLeft",
                    fill: "var(--subtle)",
                    fontSize: 9,
                  }}
                />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-strong)",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "var(--subtle)" }}
                  labelFormatter={(v: number) => timeLabel(v)}
                  formatter={(value: number) => [usd(value), "Equity"]}
                />
                <Area
                  type="monotone"
                  dataKey="equity"
                  stroke={positive ? "var(--positive)" : "var(--negative)"}
                  strokeWidth={1.5}
                  fill="url(#equityFill)"
                  isAnimationActive={false}
                  dot={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="h-24">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={samples} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} hide />
                <YAxis
                  domain={deltaDomain}
                  stroke="var(--subtle)"
                  tick={{ fontSize: 10, fill: "var(--subtle)" }}
                  tickLine={false}
                  axisLine={false}
                  width={62}
                  tickFormatter={(v: number) => v.toFixed(1)}
                />
                {/* The band inside the drift cap — the region the agent defends. */}
                <ReferenceArea
                  y1={-threshold}
                  y2={threshold}
                  fill="var(--positive)"
                  fillOpacity={0.07}
                />
                <ReferenceLine y={0} stroke="var(--subtle)" />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface-raised)",
                    border: "1px solid var(--border-strong)",
                    borderRadius: 6,
                    fontSize: 11,
                  }}
                  labelStyle={{ color: "var(--subtle)" }}
                  labelFormatter={(v: number) => timeLabel(v)}
                  formatter={(value: number) => [greek(value), "Net Δ"]}
                />
                <Line
                  type="stepAfter"
                  dataKey="netDelta"
                  stroke="var(--accent-bright)"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <div className="flex items-center justify-between px-2 text-2xs text-subtle">
            <span>Equity</span>
            <span>
              Net Δ · shaded band is the ±{threshold.toFixed(2)} drift cap
            </span>
          </div>
        </div>
      )}
    </Panel>
  );
}

/**
 * Recharts re-reconciles its entire tree on any prop change, and two charts at
 * 1 Hz was the single largest source of main-thread jank in the terminal. A new
 * sample only arrives about once a second, so comparing on sample count (plus
 * the two scalars that actually affect the render) skips the vast majority of
 * parent re-renders.
 */
export const EquityCurve = React.memo(EquityCurveImpl, (prev, next) => {
  return (
    prev.samples.length === next.samples.length &&
    prev.samples.at(-1)?.t === next.samples.at(-1)?.t &&
    prev.baseline === next.baseline &&
    prev.threshold === next.threshold
  );
});
