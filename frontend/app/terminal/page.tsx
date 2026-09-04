"use client";

import {
  Bot,
  Brain,
  LogOut,
  Magnet,
  RefreshCw,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { DeltaMagneticDial } from "@/components/DeltaMagneticDial";
import { EquityCurve, type CurveSample } from "@/components/EquityCurve";
import { ExecutionAuditStream } from "@/components/ExecutionAuditStream";
import { FlashValue } from "@/components/FlashValue";
import { GreeksTelemetry } from "@/components/GreeksTelemetry";
import { MagnoMark } from "@/components/Navbar";
import { OptionsChainTable } from "@/components/OptionsChainTable";
import { OrderSimulationModal } from "@/components/OrderSimulationModal";
import { PositionsPanel } from "@/components/PositionsPanel";
import { Badge, Button, ErrorState, StatusPip, Toggle } from "@/components/ui";
import { api, ApiError, getSessionId, setSessionId } from "@/lib/api";
import { cn, pct, usd, usdSigned } from "@/lib/format";
import { useTelemetry } from "@/lib/useTelemetry";

const MAX_SAMPLES = 900; // ~15 minutes at 1 Hz

export default function TerminalPage() {
  const router = useRouter();
  const { frame, events, status, error, reconnect, clearEvents } = useTelemetry();

  const [samples, setSamples] = React.useState<CurveSample[]>([]);
  const [shockOpen, setShockOpen] = React.useState(false);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState<
    "autopilot" | "hedge" | "end" | "dryrun" | null
  >(null);

  // Session state lives in localStorage, which the server cannot see. Resolving
  // it after mount keeps the server and first client render identical instead
  // of flashing the terminal shell and then swapping to the guard.
  const [mounted, setMounted] = React.useState(false);
  const [hasSession, setHasSession] = React.useState(false);

  React.useEffect(() => {
    setHasSession(Boolean(getSessionId()));
    setMounted(true);

    // Any 401 clears the stored id and fires this, so a session that died
    // server-side (a backend restart drops them all) surfaces the guard
    // instead of leaving every control failing silently.
    const onExpired = () => setHasSession(false);
    window.addEventListener("magno:session-expired", onExpired);
    return () => window.removeEventListener("magno:session-expired", onExpired);
  }, []);

  // Accumulate the equity/delta history from the live stream.
  React.useEffect(() => {
    if (!frame?.account?.equity) return;
    setSamples((previous) => {
      const next: CurveSample = {
        t: Math.round(frame.ts * 1000),
        equity: frame.account.equity,
        netDelta: frame.greeks?.net_delta ?? 0,
      };
      const last = previous.at(-1);
      // Drop duplicate timestamps so the chart's x-domain stays monotonic.
      if (last && next.t - last.t < 900) return previous;
      return [...previous, next].slice(-MAX_SAMPLES);
    });
  }, [frame]);

  const showNotice = React.useCallback((message: string) => {
    setNotice(message);
  }, []);

  React.useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  const toggleAutopilot = async (enabled: boolean) => {
    setBusy("autopilot");
    try {
      await api.setAutopilot(enabled);
      showNotice(
        enabled
          ? "Autopilot engaged. The agent will scan, reason and hedge on its own cadence."
          : "Autopilot disengaged. Open positions are unchanged and no longer hedged automatically.",
      );
    } catch (err) {
      showNotice(err instanceof ApiError ? err.message : "Could not change autopilot.");
    } finally {
      setBusy(null);
    }
  };

  const hedgeNow = async () => {
    setBusy("hedge");
    try {
      const result = await api.hedge(true);
      showNotice(
        result.hedged
          ? `Hedge submitted. Net Δ was ${result.net_delta.toFixed(3)}.`
          : (result.reason ?? "Nothing to hedge — the book is already neutral."),
      );
    } catch (err) {
      showNotice(err instanceof ApiError ? err.message : "Hedge failed.");
    } finally {
      setBusy(null);
    }
  };

  const runDryRun = async () => {
    setBusy("dryrun");
    try {
      const result = await api.dryRun();
      const d = result.decision;
      if (!d) {
        showNotice(result.reason ?? "Dry run found no candidates to reason over.");
      } else if (d.action === "HOLD") {
        showNotice(`${d.source} decided to HOLD. Reasoning is in the execution stream.`);
      } else {
        const verdict = result.gate?.approved
          ? "would be accepted"
          : `would be vetoed — ${result.gate?.summary ?? "gate failed"}`;
        showNotice(
          `${d.source} would ${d.side.toUpperCase()} ${d.contracts}× ${d.symbol}; ${verdict}. Nothing submitted.`,
        );
      }
    } catch (err) {
      showNotice(err instanceof ApiError ? err.message : "Dry run failed.");
    } finally {
      setBusy(null);
    }
  };

  const clearLedger = async () => {
    try {
      const { cleared } = await api.clearEvents();
      // Server-side and client-side are separate stores; both must go.
      clearEvents();
      showNotice(
        cleared
          ? `Ledger cleared — ${cleared} event(s) removed. Positions untouched.`
          : "Ledger was already empty.",
      );
    } catch (err) {
      showNotice(err instanceof ApiError ? err.message : "Could not clear the ledger.");
    }
  };

  const endSession = async () => {
    setBusy("end");
    try {
      await api.endSession();
    } catch {
      // Ending locally is what matters; a dead server is still a dead session.
    }
    setSessionId(null);
    router.push("/onboarding");
  };

  // `session` is a fresh object on every telemetry frame, so `session.universe`
  // is a new array reference each second. Keying the memo on its contents keeps
  // the identity stable, which is what lets React.memo actually skip the chain
  // table instead of re-reconciling 3,000 rows at 1 Hz.
  //
  // This must sit above the guards below: hooks cannot live after an early
  // return, or the hook count differs between renders that bail out and renders
  // that do not.
  const universeKey = (frame?.session?.universe ?? ["SPY", "QQQ", "NVDA", "AAPL"]).join(",");
  const universe = React.useMemo(() => universeKey.split(","), [universeKey]);

  // --- Guard: pre-mount ---------------------------------------------------- //
  if (!mounted) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex items-center gap-2 text-xs text-subtle">
          <StatusPip tone="neutral" />
          Restoring session…
        </div>
      </div>
    );
  }

  // --- Guard: no session --------------------------------------------------- //
  if (!hasSession || status === "unauthorized") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="panel w-full max-w-md">
          <ErrorState
            title="No active session"
            message={
              error ??
              "Connect an Alpaca paper account to open the terminal. Credentials are held in memory for the life of the session only."
            }
          />
          <div className="flex justify-center border-t border-border px-4 py-3">
            <Link
              href="/onboarding"
              className="inline-flex h-10 items-center rounded-control border border-accent bg-accent px-4 text-xs font-medium text-white transition-colors duration-100 ease-enter hover:bg-accent-bright active:translate-y-px"
            >
              Go to onboarding
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const account = frame?.account;
  const session = frame?.session;
  const greeks = frame?.greeks ?? null;
  const hedge = frame?.hedge;
  const marketOpen = frame?.clock?.is_open ?? false;
  const connected = status === "live";
  const threshold = hedge?.threshold ?? session?.envelope.delta_drift_threshold ?? 1;

  const connectionTone =
    status === "live"
      ? "positive"
      : status === "reconnecting" || status === "connecting"
        ? "warning"
        : "negative";

  const connectionLabel =
    status === "live"
      ? "Live"
      : status === "connecting"
        ? "Connecting"
        : status === "reconnecting"
          ? "Reconnecting"
          : "Offline";

  return (
    <div className="flex min-h-screen flex-col">
      {/* ---------------------------------------------------------------- */}
      {/* Header                                                            */}
      {/* ---------------------------------------------------------------- */}
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5">
          <Link href="/" className="shrink-0 rounded-control hover:opacity-80">
            <MagnoMark />
            <span className="sr-only">Magno home</span>
          </Link>

          <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />

          <div className="flex items-center gap-1.5">
            <StatusPip tone={connectionTone} pulse={status === "live"} />
            <span className="text-2xs text-muted">{connectionLabel}</span>
          </div>

          <Badge tone={marketOpen ? "positive" : "neutral"}>
            {marketOpen ? "Market open" : "Market closed"}
          </Badge>

          {session && (
            <span
              className="num hidden text-2xs text-subtle md:inline"
              title={`Alpaca paper account ${session.account_number}`}
            >
              {session.account_number}
            </span>
          )}

          {/* Headline numbers */}
          <div className="ml-auto flex items-center gap-5">
            <div className="text-right">
              <div className="th">Net account value</div>
              <div className="num text-sm font-medium text-foreground">
                {account ? (
                  <FlashValue
                    value={account.equity}
                    format={(v) => usd(v)}
                    restingClassName="text-foreground"
                    epsilon={0.004}
                  />
                ) : (
                  "—"
                )}
              </div>
            </div>

            <div className="text-right">
              <div className="th">Day P&amp;L</div>
              <div
                className={cn(
                  "num text-sm font-medium",
                  !account
                    ? "text-muted"
                    : account.day_pnl > 0
                      ? "text-positive"
                      : account.day_pnl < 0
                        ? "text-negative"
                        : "text-muted",
                )}
              >
                {account
                  ? `${usdSigned(account.day_pnl)} · ${pct(account.day_pnl_pct, 2, true)}`
                  : "—"}
              </div>
            </div>
          </div>
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border px-4 py-2">
          <div className="flex items-center gap-2">
            <Toggle
              id="autopilot"
              checked={session?.autopilot ?? false}
              onChange={toggleAutopilot}
              disabled={busy === "autopilot" || !connected}
              label="Autonomous trading"
            />
            <label htmlFor="autopilot" className="cursor-pointer text-xs text-foreground">
              <span className="flex items-center gap-1.5">
                <Bot className="h-3.5 w-3.5 text-subtle" aria-hidden="true" />
                Autopilot
              </span>
            </label>
            {session?.autopilot && (
              <Badge tone="accent">
                <StatusPip tone="accent" pulse />
                {session.cycle_count} cycles
              </Badge>
            )}
          </div>

          <span className="hidden h-5 w-px bg-border sm:block" aria-hidden="true" />

          <span className="text-2xs text-subtle">
            {session?.strategy_label ?? "—"}
          </span>

          <div className="ml-auto flex items-center gap-1.5">
            <Button
              size="sm"
              variant="secondary"
              onClick={hedgeNow}
              loading={busy === "hedge"}
              disabled={!connected}
              title="Neutralise any non-zero delta now"
            >
              {busy !== "hedge" && <Magnet className="h-3.5 w-3.5" aria-hidden="true" />}
              Hedge now
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={runDryRun}
              loading={busy === "dryrun"}
              disabled={!connected}
              title="Run scan → model → gates and stream the reasoning, without submitting anything"
            >
              {busy !== "dryrun" && (
                <Brain className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Dry run
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => setShockOpen(true)}
              disabled={!connected}
            >
              <Zap className="h-3.5 w-3.5" aria-hidden="true" />
              Shock
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={endSession}
              loading={busy === "end"}
              title="End the session and clear credentials from server memory"
            >
              {busy !== "end" && <LogOut className="h-3.5 w-3.5" aria-hidden="true" />}
              End
            </Button>
          </div>
        </div>

        {/* Connection banner */}
        {status !== "live" && (
          <div
            role="status"
            className="flex items-center gap-2 border-t border-warning/30 bg-warning/10 px-4 py-2"
          >
            <RefreshCw
              className={cn(
                "h-3.5 w-3.5 shrink-0 text-warning",
                status === "reconnecting" && "animate-spin",
              )}
              aria-hidden="true"
            />
            <p className="min-w-0 flex-1 text-2xs text-warning">
              {error ?? "Telemetry stream is not live."}
            </p>
            <Button size="sm" variant="ghost" onClick={reconnect}>
              Reconnect
            </Button>
          </div>
        )}

        {/* Upstream (Alpaca) errors surface separately from socket health. */}
        {frame && frame.errors.length > 0 && (
          <div
            role="status"
            className="border-t border-negative/30 bg-negative/5 px-4 py-2"
          >
            <p className="text-2xs text-negative">
              {frame.errors.length} upstream issue
              {frame.errors.length === 1 ? "" : "s"}: {frame.errors[0]}
            </p>
          </div>
        )}
      </header>

      {/* ---------------------------------------------------------------- */}
      {/* Workspace                                                         */}
      {/* ---------------------------------------------------------------- */}
      <main className="grid flex-1 gap-3 p-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          <DeltaMagneticDial
            netDelta={greeks?.net_delta ?? 0}
            threshold={threshold}
            deltaNotional={greeks?.delta_notional ?? 0}
            byUnderlying={greeks?.by_underlying ?? {}}
            shocked={hedge?.shocked ?? false}
            className={!frame ? "opacity-60" : undefined}
          />

          <GreeksTelemetry
            greeks={greeks}
            volSurface={frame?.vol_surface ?? []}
            loading={!frame}
          />

          <OptionsChainTable
            universe={universe}
            contractQty={session?.contract_qty ?? 1}
            marketOpen={marketOpen}
            onTraded={showNotice}
            className="min-h-[24rem] flex-1"
          />
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          <EquityCurve
            samples={samples}
            baseline={session?.equity_at_open ?? account?.last_equity ?? 100_000}
            threshold={threshold}
          />

          <PositionsPanel
            positions={frame?.positions ?? []}
            loading={!frame}
            onNotice={showNotice}
            className="max-h-[22rem]"
          />

          <ExecutionAuditStream
            events={events}
            connected={connected}
            onClear={clearLedger}
            className="min-h-[26rem] flex-1"
          />
        </div>
      </main>

      {/* Risk envelope footer — always visible so the operative limits are
          never more than a glance away. */}
      {session && (
        <footer className="border-t border-border px-4 py-2">
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-2xs text-subtle">
            <li>
              Spread cap{" "}
              <span className="num text-muted">{pct(session.envelope.max_spread_pct)}</span>
            </li>
            <li>
              Allocation cap{" "}
              <span className="num text-muted">
                {pct(session.envelope.max_allocation_pct, 0)}
              </span>
            </li>
            <li>
              Drift cap{" "}
              <span className="num text-muted">
                ±{session.envelope.delta_drift_threshold.toFixed(2)}Δ
              </span>
            </li>
            <li>
              Loss breaker{" "}
              <span className="num text-muted">
                {pct(session.envelope.max_daily_loss_pct, 0)}
              </span>
            </li>
            <li>
              Positions{" "}
              <span className="num text-muted">
                {greeks?.gross_option_positions ?? 0}/{session.envelope.max_open_positions}
              </span>
            </li>
            <li>
              DTE{" "}
              <span className="num text-muted">
                {session.envelope.min_dte}–{session.envelope.max_dte}d
              </span>
            </li>
          </ul>
        </footer>
      )}

      {/* Notice toast */}
      {notice && (
        <div
          role="status"
          aria-live="polite"
          className={cn(
            "fixed bottom-4 right-4 z-40 flex max-w-md items-start gap-3",
            "rounded-card border border-border-strong bg-surface-raised px-4 py-3 shadow-2xl",
            "animate-fade-up",
          )}
        >
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-foreground">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss notification"
            className="-mr-1 -mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded text-muted transition-colors duration-100 ease-enter hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      )}

      <OrderSimulationModal
        open={shockOpen}
        onClose={() => setShockOpen(false)}
        universe={universe}
        activeShocks={hedge?.shocks ?? {}}
        threshold={threshold}
        onChanged={() => showNotice("Shock state updated. Watch the delta dial respond.")}
      />
    </div>
  );
}
