"use client";

import { ArrowRight, Info, X, Zap } from "lucide-react";
import * as React from "react";

import { api, ApiError } from "@/lib/api";
import { cn, greek, num, pct, usd } from "@/lib/format";
import type { HedgeIntent } from "@/lib/types";

import { Badge, Button, ErrorState, Panel } from "./ui";

/**
 * Judge-facing shock harness.
 *
 * The book is re-priced through Black-Scholes at the shocked spot with implied
 * vol held constant, so the delta drift that appears is the real gamma effect
 * on the real positions — not an animation. While a shock is active the hedge
 * engine still computes and logs the corrective order but does not submit it,
 * because the move did not actually happen and a real fill against a simulated
 * price would corrupt the P&L the agent is judged on.
 */

const PRESETS = [-0.05, -0.02, -0.01, 0.01, 0.02, 0.05];

interface ShockResult {
  delta_before: number;
  delta_after: number;
  intents: HedgeIntent[];
}

export function OrderSimulationModal({
  open,
  onClose,
  universe,
  activeShocks,
  threshold,
  onChanged,
}: {
  open: boolean;
  onClose: () => void;
  universe: string[];
  activeShocks: Record<string, number>;
  threshold: number;
  onChanged?: () => void;
}) {
  const [underlying, setUnderlying] = React.useState(universe[0] ?? "SPY");
  const [magnitude, setMagnitude] = React.useState(0.02);
  const [result, setResult] = React.useState<ShockResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const panelRef = React.useRef<HTMLDivElement>(null);
  const restoreFocusRef = React.useRef<HTMLElement | null>(null);

  // Focus management: capture the trigger, move focus in, restore on close.
  React.useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const first = panelRef.current?.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    first?.focus();
    return () => restoreFocusRef.current?.focus();
  }, [open]);

  // Escape closes; Tab cycles within the drawer.
  React.useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;

      const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusables || focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, onClose]);

  const applyShock = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.shock(underlying, magnitude);
      setResult({
        delta_before: response.delta_before,
        delta_after: response.delta_after,
        intents: response.intents,
      });
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not apply the shock.");
    } finally {
      setBusy(false);
    }
  };

  const clearShocks = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.clearShocks();
      setResult(null);
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not clear the shock.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const shockCount = Object.keys(activeShocks).length;
  const drift = result ? Math.abs(result.delta_after) >= threshold : false;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close shock simulator"
        onClick={onClose}
        className="absolute inset-0 bg-background/80 backdrop-blur-sm"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shock-title"
        className={cn(
          "relative flex h-full w-full max-w-md flex-col border-l border-border bg-surface",
          "shadow-2xl animate-fade-up overflow-y-auto",
        )}
      >
        <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-border bg-surface px-4 py-3">
          <div>
            <h2
              id="shock-title"
              className="flex items-center gap-2 text-sm font-medium text-foreground"
            >
              <Zap className="h-4 w-4 text-accent-bright" aria-hidden="true" />
              Shock simulator
            </h2>
            <p className="mt-0.5 text-2xs leading-relaxed text-muted">
              Re-price the live book under a hypothetical move and watch the hedge
              engine respond.
            </p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={onClose}
            aria-label="Close shock simulator"
            className="-mr-1 -mt-1"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </header>

        <div className="flex-1 space-y-5 px-4 py-4">
          {/* Underlying */}
          <div>
            <span className="th mb-2 block">Underlying</span>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Shock underlying">
              {universe.map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => setUnderlying(name)}
                  aria-pressed={underlying === name}
                  className={cn(
                    "num h-9 min-w-[3.5rem] rounded-control px-3 text-xs font-medium",
                    "transition-colors duration-100 ease-enter active:translate-y-px",
                    underlying === name
                      ? "bg-accent text-white"
                      : "bg-surface-raised text-muted hover:text-foreground",
                  )}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>

          {/* Magnitude */}
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <span className="th">Price move</span>
              <span
                className={cn(
                  "num text-sm font-medium",
                  magnitude > 0 ? "text-positive" : "text-negative",
                )}
              >
                {magnitude > 0 ? "+" : "−"}
                {(Math.abs(magnitude) * 100).toFixed(1)}%
              </span>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setMagnitude(value)}
                  aria-pressed={magnitude === value}
                  className={cn(
                    "num h-9 min-w-[3.5rem] rounded-control px-3 text-xs font-medium",
                    "transition-colors duration-100 ease-enter active:translate-y-px",
                    magnitude === value
                      ? "bg-surface-raised text-foreground ring-1 ring-inset ring-accent"
                      : "bg-surface-raised text-muted hover:text-foreground",
                  )}
                >
                  {value > 0 ? "+" : "−"}
                  {(Math.abs(value) * 100).toFixed(0)}%
                </button>
              ))}
            </div>

            <label htmlFor="shock-range" className="sr-only">
              Shock magnitude
            </label>
            <input
              id="shock-range"
              type="range"
              min={-10}
              max={10}
              step={0.5}
              value={magnitude * 100}
              onChange={(e) => setMagnitude(Number(e.target.value) / 100)}
              className="mt-3 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-surface-raised accent-accent"
            />
            <div className="mt-1 flex justify-between text-2xs text-subtle">
              <span className="num">−10%</span>
              <span className="num">0%</span>
              <span className="num">+10%</span>
            </div>
          </div>

          <div className="flex gap-2">
            <Button variant="primary" onClick={applyShock} loading={busy} className="flex-1">
              Apply shock
            </Button>
            <Button
              variant="secondary"
              onClick={clearShocks}
              disabled={busy || shockCount === 0}
              title={shockCount === 0 ? "No active shocks" : "Re-mark the book to live prices"}
            >
              Clear
            </Button>
          </div>

          {error && (
            <div className="panel">
              <ErrorState title="Shock failed" message={error} onRetry={applyShock} />
            </div>
          )}

          {/* Active shocks */}
          {shockCount > 0 && (
            <div className="panel px-3 py-2.5">
              <span className="th">Active shocks</span>
              <ul className="mt-1.5 space-y-1">
                {Object.entries(activeShocks).map(([name, value]) => (
                  <li key={name} className="flex items-center justify-between text-xs">
                    <span className="num text-foreground">{name}</span>
                    <span
                      className={cn("num", value > 0 ? "text-positive" : "text-negative")}
                    >
                      {value > 0 ? "+" : "−"}
                      {(Math.abs(value) * 100).toFixed(1)}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Result */}
          {result && (
            <Panel title="Simulated response" className="animate-fade-up">
              <div className="space-y-3 px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="th">Net Δ before</div>
                    <div className="num mt-0.5 text-lg text-muted">
                      {greek(result.delta_before)}
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-subtle" aria-hidden="true" />
                  <div className="text-right">
                    <div className="th">Net Δ after</div>
                    <div
                      className={cn(
                        "num mt-0.5 text-lg font-medium",
                        drift ? "text-accent-bright" : "text-foreground",
                      )}
                    >
                      {greek(result.delta_after)}
                    </div>
                  </div>
                </div>

                {drift ? (
                  <Badge tone="accent">
                    Breached ±{threshold.toFixed(2)}Δ drift cap — hedge engine engaged
                  </Badge>
                ) : (
                  <Badge tone="positive">
                    Still inside the ±{threshold.toFixed(2)}Δ drift cap
                  </Badge>
                )}

                {result.intents.length > 0 && (
                  <div className="border-t border-border pt-3">
                    <span className="th">Corrective orders</span>
                    <ul className="mt-2 space-y-2">
                      {result.intents.map((intent) => (
                        <li key={intent.underlying} className="text-xs">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="num text-foreground">
                              <span
                                className={cn(
                                  "font-medium",
                                  intent.side === "sell" ? "text-negative" : "text-positive",
                                )}
                              >
                                {intent.side.toUpperCase()}
                              </span>{" "}
                              {num(intent.qty, 3)} {intent.underlying}
                            </span>
                            <span className="num text-2xs text-subtle">
                              {usd(intent.notional)}
                            </span>
                          </div>
                          <p className="mt-0.5 text-2xs leading-relaxed text-muted">
                            Δ {greek(intent.net_delta_before)} →{" "}
                            {greek(intent.projected_delta_after)} at{" "}
                            {usd(intent.spot)} spot
                          </p>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Panel>
          )}

          <div className="flex gap-2 rounded-card border border-border bg-surface-raised px-3 py-2.5">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-subtle" aria-hidden="true" />
            <p className="text-2xs leading-relaxed text-muted">
              Positions are re-priced through Black-Scholes at the shocked spot with
              implied vol held constant, so the drift shown is the real gamma effect on
              your real book. While a shock is active the hedge engine computes and logs
              its corrective order but does not submit it — the move did not happen, and a
              live fill against a simulated price would corrupt your P&amp;L. Clear the
              shock to resume real hedging.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
