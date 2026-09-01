"use client";

import { AlertCircle, Clock, RefreshCw, ShieldX, Table2 } from "lucide-react";
import * as React from "react";

import { api, ApiError } from "@/lib/api";
import { cn, expiryLabel, greek, int, num, pct, usd } from "@/lib/format";
import type { ChainContract } from "@/lib/types";

import { Badge, Button, EmptyState, ErrorState, Panel, TableSkeleton } from "./ui";

/**
 * Live option chain with the pre-trade gate verdict attached to every row.
 *
 * The gate column is the point of this table. A row that cannot be traded says
 * *which* gate stopped it, so the rejection is legible rather than a greyed-out
 * button with no explanation.
 */

const GATE_LABELS: Record<string, string> = {
  SPREAD_TOO_WIDE: "Spread",
  SPREAD_NO_QUOTE: "No quote",
  SPREAD_ZERO_BID: "No bid",
  SPREAD_CROSSED: "Crossed",
  SPREAD_NO_MID: "No mid",
  PRICE_TOO_LOW: "Too cheap",
  PRICE_TOO_HIGH: "Too rich",
  DTE_TOO_NEAR: "Near expiry",
  DTE_TOO_FAR: "Far expiry",
  OI_TOO_THIN: "Thin OI",
  IV_UNSOLVABLE: "IV",
  IV_IMPLAUSIBLE: "IV",
  ALLOC_EXCEEDS_CAP: "Size cap",
  ALLOC_NO_BP: "No BP",
  CONCENTRATION_CAP: "Position cap",
  DAILY_LOSS_HALT: "Loss halt",
  MARKET_CLOSED: "Closed",
};

function gateLabel(code: string) {
  return GATE_LABELS[code] ?? code.replace(/_/g, " ").toLowerCase();
}

function OptionsChainTableImpl({
  universe,
  contractQty,
  marketOpen,
  onTraded,
  className,
}: {
  universe: string[];
  contractQty: number;
  marketOpen: boolean;
  onTraded?: (message: string) => void;
  className?: string;
}) {
  const [underlying, setUnderlying] = React.useState(universe[0] ?? "SPY");
  const [right, setRight] = React.useState<"C" | "P" | null>(null);
  const [rows, setRows] = React.useState<ChainContract[] | null>(null);
  const [spot, setSpot] = React.useState<number | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [busySymbol, setBusySymbol] = React.useState<string | null>(null);
  const [onlyApproved, setOnlyApproved] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.chain(underlying, right ?? undefined);
      setRows(result.contracts);
      setSpot(result.spot);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load the option chain.");
      setRows(null);
    } finally {
      setLoading(false);
    }
  }, [underlying, right]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const trade = async (contract: ChainContract, side: "buy" | "sell") => {
    setBusySymbol(contract.symbol);
    try {
      const result = await api.submitOption(
        contract.symbol,
        side,
        contractQty,
        "Operator-initiated from the chain table.",
      );
      onTraded?.(
        `${side.toUpperCase()} ${contractQty}× ${contract.symbol} submitted at $${result.limit_price.toFixed(2)} limit.`,
      );
      await load();
    } catch (err) {
      onTraded?.(err instanceof ApiError ? err.message : "Order failed.");
    } finally {
      setBusySymbol(null);
    }
  };

  const visible = React.useMemo(() => {
    if (!rows) return null;
    return onlyApproved ? rows.filter((r) => r.gate?.approved) : rows;
  }, [rows, onlyApproved]);

  const approvedCount = rows?.filter((r) => r.gate?.approved).length ?? 0;

  return (
    <Panel
      title="Options chain"
      subtitle={
        spot
          ? `${underlying} spot ${usd(spot)} · ${approvedCount} of ${rows?.length ?? 0} contracts pass every contract-level gate`
          : "Live NBBO with pre-trade gate verdicts"
      }
      className={className}
      bodyClassName="flex min-h-0 flex-col"
      action={
        <Button
          size="sm"
          variant="ghost"
          onClick={load}
          loading={loading}
          aria-label="Refresh option chain"
        >
          {!loading && <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
          Refresh
        </Button>
      }
    >
      {/* Filters */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-1" role="group" aria-label="Underlying">
          {universe.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setUnderlying(name)}
              aria-pressed={underlying === name}
              className={cn(
                "num h-8 rounded-control px-2.5 text-xs font-medium",
                "transition-colors duration-100 ease-enter active:translate-y-px",
                underlying === name
                  ? "bg-accent text-white"
                  : "text-muted hover:bg-surface-raised hover:text-foreground",
              )}
            >
              {name}
            </button>
          ))}
        </div>

        <span className="h-4 w-px bg-border" aria-hidden="true" />

        <div className="flex items-center gap-1" role="group" aria-label="Contract type">
          {(
            [
              [null, "All"],
              ["C", "Calls"],
              ["P", "Puts"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={label}
              type="button"
              onClick={() => setRight(value)}
              aria-pressed={right === value}
              className={cn(
                "h-8 rounded-control px-2.5 text-xs font-medium",
                "transition-colors duration-100 ease-enter active:translate-y-px",
                right === value
                  ? "bg-surface-raised text-foreground ring-1 ring-inset ring-border-strong"
                  : "text-muted hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <label className="ml-auto flex cursor-pointer items-center gap-2 text-2xs text-muted">
          <input
            type="checkbox"
            checked={onlyApproved}
            onChange={(e) => setOnlyApproved(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border-strong bg-background accent-accent"
          />
          Gate-approved only
        </label>
      </div>

      {/* Market-hours notice. The clock is a single global fact, so it is stated
          once here rather than stamped onto all 3,000 rows. */}
      {!marketOpen && (
        <div className="flex shrink-0 items-center gap-2 border-b border-warning/25 bg-warning/[0.07] px-4 py-2">
          <Clock className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
          <p className="text-2xs leading-relaxed text-warning">
            US market is closed. Gate verdicts below are live and contract-specific,
            but no order can be submitted until the open.
          </p>
        </div>
      )}

      {/* Body */}
      <div className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <ErrorState
            title="Chain unavailable"
            message={error}
            onRetry={load}
            retryLabel="Try again"
          />
        ) : loading && !rows ? (
          <TableSkeleton rows={8} cols={8} />
        ) : !visible || visible.length === 0 ? (
          <EmptyState
            icon={onlyApproved ? ShieldX : Table2}
            title={onlyApproved ? "Nothing cleared the gates" : "No contracts in range"}
            description={
              onlyApproved
                ? "Every contract in this chain failed at least one pre-trade gate. Turn off the filter to see which gate stopped each one."
                : `No ${underlying} contracts matched the configured DTE and moneyness window. Widen the DTE range in your risk envelope, or pick another underlying.`
            }
            action={
              onlyApproved ? (
                <Button size="sm" onClick={() => setOnlyApproved(false)}>
                  Show all contracts
                </Button>
              ) : undefined
            }
          />
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-surface-raised">
              <tr className="border-b border-border">
                <th className="th px-3 py-2 text-left">Contract</th>
                <th className="th px-3 py-2 text-right">Bid</th>
                <th className="th px-3 py-2 text-right">Ask</th>
                <th className="th px-3 py-2 text-right">Spread</th>
                <th className="th hidden px-3 py-2 text-right md:table-cell">OI</th>
                <th className="th px-3 py-2 text-right">IV</th>
                <th className="th px-3 py-2 text-right">Δ</th>
                <th className="th hidden px-3 py-2 text-right lg:table-cell">Γ</th>
                <th className="th hidden px-3 py-2 text-right lg:table-cell">Θ/day</th>
                <th className="th px-3 py-2 text-left">Gate</th>
                <th className="th px-3 py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => {
                const approved = row.gate?.approved ?? false;
                const rejection = row.gate?.checks.find((c) => c.verdict === "REJECT");
                const wide =
                  row.spread_pct !== null && row.spread_pct > 0.05;
                const atm = Math.abs(row.moneyness) < 0.01;
                const busy = busySymbol === row.symbol;

                return (
                  <tr
                    key={row.symbol}
                    className={cn(
                      "border-b border-border/60 transition-colors duration-100 ease-enter",
                      "hover:bg-surface-raised",
                      atm && "bg-accent/[0.04]",
                    )}
                  >
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "num inline-flex h-4 w-4 shrink-0 items-center justify-center rounded text-2xs font-medium",
                            row.right === "C"
                              ? "bg-accent-dim/50 text-accent-bright"
                              : "bg-border-strong text-muted",
                          )}
                          aria-label={row.right === "C" ? "Call" : "Put"}
                        >
                          {row.right}
                        </span>
                        <span className="num text-foreground">
                          {row.strike % 1 === 0 ? row.strike.toFixed(0) : row.strike.toFixed(2)}
                        </span>
                        {atm && <Badge tone="accent">ATM</Badge>}
                      </div>
                      <div className="num mt-0.5 text-2xs text-subtle">
                        {expiryLabel(row.expiry)} · {row.dte.toFixed(0)}d
                      </div>
                    </td>
                    <td className="num px-3 py-2 text-right text-muted">
                      {row.bid === null ? "—" : num(row.bid)}
                    </td>
                    <td className="num px-3 py-2 text-right text-muted">
                      {row.ask === null ? "—" : num(row.ask)}
                    </td>
                    <td
                      className={cn(
                        "num px-3 py-2 text-right",
                        wide ? "text-negative" : "text-foreground",
                      )}
                    >
                      {pct(row.spread_pct)}
                    </td>
                    <td className="num hidden px-3 py-2 text-right text-muted md:table-cell">
                      {int(row.open_interest)}
                    </td>
                    <td className="num px-3 py-2 text-right text-muted">
                      {pct(row.iv, 1)}
                    </td>
                    <td className="num px-3 py-2 text-right text-foreground">
                      {row.greeks ? greek(row.greeks.delta) : "—"}
                    </td>
                    <td className="num hidden px-3 py-2 text-right text-muted lg:table-cell">
                      {row.greeks ? num(row.greeks.gamma, 4) : "—"}
                    </td>
                    <td className="num hidden px-3 py-2 text-right text-muted lg:table-cell">
                      {row.greeks ? num(row.greeks.theta * 100, 2) : "—"}
                    </td>
                    <td className="px-3 py-2">
                      {approved ? (
                        <Badge tone="positive">Clear</Badge>
                      ) : (
                        <span
                          className="inline-flex items-center gap-1"
                          title={rejection?.message ?? row.gate?.summary}
                        >
                          <Badge tone="negative">
                            <AlertCircle className="h-2.5 w-2.5" aria-hidden="true" />
                            {rejection ? gateLabel(rejection.code) : "Blocked"}
                          </Badge>
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!approved || !marketOpen}
                          loading={busy}
                          onClick={() => trade(row, "buy")}
                          title={
                            !marketOpen
                              ? "Market is closed"
                              : !approved
                                ? row.gate?.summary
                                : `Buy ${contractQty} contract(s)`
                          }
                        >
                          Buy
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={!approved || !marketOpen}
                          onClick={() => trade(row, "sell")}
                          title={
                            !marketOpen
                              ? "Market is closed"
                              : !approved
                                ? row.gate?.summary
                                : `Sell ${contractQty} contract(s)`
                          }
                        >
                          Sell
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </Panel>
  );
}

/**
 * The terminal re-renders at 1 Hz as telemetry frames arrive. Reconciling this
 * table on every one of those ticks kept the main thread busy long enough to
 * drop pointer events — the filter buttons genuinely needed two presses. None
 * of these props change on a telemetry tick, so memoising removes the work
 * entirely.
 */
export const OptionsChainTable = React.memo(OptionsChainTableImpl);
