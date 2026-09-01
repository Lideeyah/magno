"use client";

import { Briefcase, X } from "lucide-react";
import * as React from "react";

import { api, ApiError } from "@/lib/api";
import { cn, greek, num, occLabel, usd, usdSigned } from "@/lib/format";
import type { Position } from "@/lib/types";

import { Badge, Button, EmptyState, Panel, TableSkeleton } from "./ui";

export function PositionsPanel({
  positions,
  loading,
  onNotice,
  className,
}: {
  positions: Position[];
  loading: boolean;
  onNotice?: (message: string) => void;
  className?: string;
}) {
  const [closing, setClosing] = React.useState<string | null>(null);

  const close = async (symbol: string) => {
    setClosing(symbol);
    try {
      await api.closePosition(symbol);
      onNotice?.(`Close order submitted for ${symbol}.`);
    } catch (error) {
      onNotice?.(error instanceof ApiError ? error.message : "Close failed.");
    } finally {
      setClosing(null);
    }
  };

  const options = positions.filter((p) => p.asset_class === "us_option");
  const equities = positions.filter((p) => p.asset_class === "us_equity");
  const totalPnl = positions.reduce((acc, p) => acc + p.unrealized_pl, 0);

  return (
    <Panel
      title="Positions"
      subtitle={
        positions.length
          ? `${options.length} option${options.length === 1 ? "" : "s"} · ${equities.length} hedge leg${equities.length === 1 ? "" : "s"}`
          : "Options and their equity hedge legs"
      }
      className={className}
      bodyClassName="min-h-0 overflow-auto"
      action={
        positions.length > 0 ? (
          <span className={cn("num text-xs", totalPnl >= 0 ? "text-positive" : "text-negative")}>
            {usdSigned(totalPnl)}
          </span>
        ) : undefined
      }
    >
      {loading && positions.length === 0 ? (
        <TableSkeleton rows={4} cols={5} />
      ) : positions.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="Flat"
          description="No open positions. The agent opens its first contract on the next reasoning cycle once autopilot is engaged, or you can trade directly from the chain."
        />
      ) : (
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-surface-raised">
            <tr className="border-b border-border">
              <th className="th px-3 py-2 text-left">Instrument</th>
              <th className="th px-3 py-2 text-right">Qty</th>
              <th className="th px-3 py-2 text-right">Mark</th>
              <th className="th hidden px-3 py-2 text-right sm:table-cell">Δ exp.</th>
              <th className="th px-3 py-2 text-right">P&amp;L</th>
              <th className="th px-3 py-2 text-right sr-only">Close</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => {
              const isOption = position.asset_class === "us_option";
              return (
                <tr
                  key={position.symbol}
                  className="border-b border-border/60 transition-colors duration-100 ease-enter hover:bg-surface-raised"
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <span className="num truncate text-foreground">
                        {isOption ? occLabel(position.symbol) : position.symbol}
                      </span>
                      {!isOption && <Badge tone="accent">Hedge</Badge>}
                    </div>
                    {isOption && position.dte !== null && (
                      <div className="num mt-0.5 text-2xs text-subtle">
                        {position.dte.toFixed(0)}d ·{" "}
                        {position.greeks ? `IV ${(position.greeks.iv * 100).toFixed(1)}%` : "—"}
                      </div>
                    )}
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2 text-right",
                      position.qty >= 0 ? "text-foreground" : "text-negative",
                    )}
                  >
                    {num(position.qty, isOption ? 0 : 3)}
                  </td>
                  <td className="num px-3 py-2 text-right text-muted">
                    {usd(position.current_price)}
                  </td>
                  <td className="num hidden px-3 py-2 text-right text-muted sm:table-cell">
                    {greek(position.delta_exposure, 2)}
                  </td>
                  <td
                    className={cn(
                      "num px-3 py-2 text-right",
                      position.unrealized_pl > 0
                        ? "text-positive"
                        : position.unrealized_pl < 0
                          ? "text-negative"
                          : "text-muted",
                    )}
                  >
                    {usdSigned(position.unrealized_pl)}
                  </td>
                  <td className="px-2 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={closing === position.symbol}
                      onClick={() => close(position.symbol)}
                      aria-label={`Close ${position.symbol}`}
                      title={`Close ${position.symbol}`}
                    >
                      {closing !== position.symbol && (
                        <X className="h-3.5 w-3.5" aria-hidden="true" />
                      )}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
