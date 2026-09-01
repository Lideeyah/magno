"use client";

import * as React from "react";

import { cn } from "@/lib/format";

/**
 * Risk-dimension comparison, built as a dense financial table rather than a
 * marketing grid. Each row's claim is one Magno makes in code — the gate codes
 * and behaviours named here all exist in `backend/app/quant/risk_gate.py` and
 * `hedge_engine.py`.
 */

const ROWS = [
  {
    dimension: "Execution slippage",
    standard: "Pays heavy markups on illiquid contracts",
    magnoLead: "Hard 5% spread gate",
    magno: "Vetoes bad pricing before the order is constructed",
  },
  {
    dimension: "Market volatility",
    standard: "Ignores delta drift; bleeds on sharp moves",
    magnoLead: "Continuous dynamic hedging",
    magno: "Rebalances exposure back to 0.00Δ every five seconds",
  },
  {
    dimension: "Cross-asset contagion",
    standard: "Nets SPY and QQQ together, creating a basis bet",
    magnoLead: "Per-underlying isolation",
    magno: "Independent Greek buckets, hedged per name",
  },
  {
    dimension: "Drawdown circuit breakers",
    standard: "Freezes the account, leaving open options trapped",
    magnoLead: "Non-trapping breaker",
    magno: "Halts new risk while hedging stays live",
  },
  {
    dimension: "Model reliability",
    standard: "Unconstrained LLMs hallucinate tickers",
    magnoLead: "Closed-menu schema",
    magno: "Reasoner picks only from pre-cleared candidates",
  },
];

export function ComparisonMatrix() {
  return (
    <div className="overflow-x-auto rounded-lg border border-white/[0.08]">
      <table className="w-full min-w-[52rem] border-collapse text-left">
        <thead>
          <tr className="border-b border-white/[0.08]">
            <th className="num w-[16rem] px-5 py-3 text-2xs uppercase tracking-[0.14em] text-subtle">
              Risk dimension
            </th>
            <th className="num px-5 py-3 text-2xs uppercase tracking-[0.14em] text-subtle">
              Standard trading bots
            </th>
            <th className="num px-5 py-3 text-2xs uppercase tracking-[0.14em] text-accent-bright">
              Magno autonomous desk
            </th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map((row) => (
            <tr
              key={row.dimension}
              className={cn(
                "group border-b border-white/[0.06] last:border-b-0",
                "transition-colors duration-100 hover:bg-white/[0.04]",
              )}
            >
              <th
                scope="row"
                className={cn(
                  "relative px-5 py-4 text-sm font-medium text-foreground",
                  // Cobalt left-edge marker on hover.
                  "before:absolute before:inset-y-0 before:left-0 before:w-px before:bg-transparent",
                  "before:transition-colors before:duration-100 group-hover:before:bg-accent",
                )}
              >
                {row.dimension}
              </th>
              <td className="px-5 py-4 text-xs leading-relaxed text-muted">{row.standard}</td>
              <td className="px-5 py-4 text-xs leading-relaxed text-muted">
                <span className="block font-medium text-foreground">{row.magnoLead}</span>
                <span className="mt-0.5 block">{row.magno}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
