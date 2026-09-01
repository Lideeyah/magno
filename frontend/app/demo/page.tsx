"use client";

import { Brain, Radar, ShieldCheck } from "lucide-react";
import * as React from "react";

import { DeltaMagneticDial } from "@/components/DeltaMagneticDial";
import { DemoChrome, Spotlight } from "@/components/demo/DemoStage";
import {
  STAGES,
  TOTAL_SECONDS,
  stageAt,
  stageProgress,
} from "@/components/demo/sequence";
import { ExecutionAuditStream } from "@/components/ExecutionAuditStream";
import { GreeksTelemetry } from "@/components/GreeksTelemetry";
import { PositionsPanel } from "@/components/PositionsPanel";
import { Badge, Button, Panel } from "@/components/ui";
import { API_BASE, getSessionId, setSessionId } from "@/lib/api";
import { cn, greek, num, usd, usdSigned } from "@/lib/format";
import type { AuditEvent, GateResult } from "@/lib/types";
import { useTelemetry } from "@/lib/useTelemetry";

/**
 * Isolated auto-demo sandbox.
 *
 * Runs on its own port with its own build directory so it cannot disturb the
 * primary terminal. It is a strictly *read-only* client: it renders live
 * telemetry from the same backend and never submits an order, never engages
 * autopilot, and never mutates the risk envelope. Nothing on this page can
 * change the book being recorded.
 */

const TICK_MS = 100;

export default function DemoPage() {
  const { frame, events, status } = useTelemetry();
  const [mounted, setMounted] = React.useState(false);
  const [sessionReady, setSessionReady] = React.useState(false);
  const [manualId, setManualId] = React.useState("");

  // The demo backend mints its own session from DEMO_ALPACA_* credentials at
  // startup, so the page connects with no manual step. A ?session= override is
  // still honoured for attaching to a specific existing session.
  const [bootError, setBootError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("session");
    if (fromUrl) {
      setSessionId(fromUrl);
      window.history.replaceState({}, "", window.location.pathname);
      setSessionReady(true);
      setMounted(true);
      return;
    }

    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/demo/session`);
        const body = await res.json();
        if (body.ready && body.session_id) {
          setSessionId(body.session_id);
          setSessionReady(true);
        } else {
          setBootError(body.error ?? "Demo backend has no session.");
          setSessionReady(Boolean(getSessionId()));
        }
      } catch {
        setBootError(
          `Cannot reach the demo backend at ${API_BASE}. Start it with: uvicorn app.demo_main:app --port 8001`,
        );
        setSessionReady(Boolean(getSessionId()));
      } finally {
        setMounted(true);
      }
    })();
  }, []);

  // --- the sequencer -------------------------------------------------------
  const [elapsed, setElapsed] = React.useState(0);
  const [running, setRunning] = React.useState(false);

  React.useEffect(() => {
    if (!running) return;
    const started = performance.now() - elapsed * 1000;
    const timer = setInterval(() => {
      const next = (performance.now() - started) / 1000;
      if (next >= TOTAL_SECONDS) {
        setElapsed(TOTAL_SECONDS);
        setRunning(false);
      } else {
        setElapsed(next);
      }
    }, TICK_MS);
    return () => clearInterval(timer);
    // `elapsed` is intentionally omitted: including it would restart the
    // interval on every tick and drift the clock.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  // Interaction is locked during playback so a stray click cannot derail a take.
  React.useEffect(() => {
    if (!running) return;
    const swallow = (e: Event) => {
      const el = e.target as HTMLElement;
      if (el.closest("[data-demo-control]")) return;
      e.preventDefault();
      e.stopPropagation();
    };
    document.addEventListener("click", swallow, true);
    return () => document.removeEventListener("click", swallow, true);
  }, [running]);

  const stage = stageAt(elapsed);
  const progress = stageProgress(elapsed, stage);
  const live = status === "live";

  const account = frame?.account;
  const greeks = frame?.greeks ?? null;
  const threshold = frame?.hedge?.threshold ?? 8;

  // Stage 1 replays a breach so the correction is visible on camera. It is
  // explicitly labelled: the live reading is shown alongside, unaltered.
  const replayDelta = React.useMemo(() => {
    if (stage.id !== "HERO_DIAL") return null;
    if (progress < 0.25) return null;
    if (progress < 0.55) return 12.5; // deflection held long enough to read
    return null;
  }, [stage.id, progress]);

  const liveDelta = greeks?.net_delta ?? 0;
  const shownDelta = replayDelta ?? liveDelta;

  const reasoning = React.useMemo(
    () => events.filter((e) => e.category === "reasoning").slice(-6),
    [events],
  );
  const gateEvent = React.useMemo(
    () =>
      [...events]
        .reverse()
        .find((e) => e.category === "gate" && (e.data?.gate as GateResult)?.checks?.length),
    [events],
  );
  const hedgeEvents = React.useMemo(
    () => events.filter((e) => e.category === "hedge" || e.category === "risk").slice(-8),
    [events],
  );

  if (!mounted) return null;

  // --- session handoff -----------------------------------------------------
  if (!sessionReady || status === "unauthorized") {
    return (
      <main className="flex min-h-screen items-center justify-center px-6">
        <div className="panel w-full max-w-lg p-6">
          <h1 className="text-lg font-semibold text-foreground">Demo sandbox</h1>
          <p className="mt-2 text-xs leading-relaxed text-muted">
            The demo backend mints its own Alpaca session from{" "}
            <code className="num text-foreground">DEMO_ALPACA_*</code> credentials,
            so this page normally connects on its own.
          </p>
          {bootError && (
            <p className="mt-3 rounded-card border border-negative/30 bg-negative/5 px-3 py-2 text-2xs leading-relaxed text-negative">
              {bootError}
            </p>
          )}
          <p className="mt-3 text-2xs leading-relaxed text-subtle">
            Set the keys in <code className="num text-foreground">backend/.env.demo</code>{" "}
            and start the demo backend, or attach to an existing session id below.
          </p>
          <div className="mt-4 flex gap-2">
            <input
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              placeholder="session id"
              className="num h-10 flex-1 rounded-control border border-border bg-background px-3 text-xs text-foreground placeholder:text-subtle"
            />
            <Button
              variant="primary"
              data-demo-control
              onClick={() => {
                if (!manualId.trim()) return;
                setSessionId(manualId.trim());
                setSessionReady(true);
                window.location.reload();
              }}
            >
              Attach
            </Button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen">
      <DemoChrome
        elapsed={elapsed}
        total={TOTAL_SECONDS}
        stage={stage}
        running={running}
        live={live}
      />

      {/* Run controls — the only interactive elements during playback. */}
      <div className="mx-auto flex max-w-[1600px] items-center gap-2 px-6 py-3">
        <Button
          variant="primary"
          data-demo-control
          onClick={() => setRunning((r) => !r)}
        >
          {running ? "Pause" : elapsed >= TOTAL_SECONDS ? "Replay" : "Start 120s run"}
        </Button>
        <Button
          variant="ghost"
          data-demo-control
          onClick={() => {
            setRunning(false);
            setElapsed(0);
          }}
        >
          Reset
        </Button>
        {running && (
          <span className="num text-2xs text-subtle">
            Interaction locked during playback
          </span>
        )}
        <span className="ml-auto num text-2xs text-subtle">
          Read-only · this page cannot trade
        </span>
      </div>

      <main className="mx-auto grid max-w-[1600px] gap-3 px-6 pb-16 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-3">
          {/* 1 — Delta dial */}
          <Spotlight active={stage.id === "HERO_DIAL"}>
            <div className="relative">
              {replayDelta !== null && (
                <div className="absolute right-3 top-3 z-10">
                  <Badge tone="warning">
                    Replay · simulated +2% NVDA shock
                  </Badge>
                </div>
              )}
              <DeltaMagneticDial
                netDelta={shownDelta}
                threshold={threshold}
                deltaNotional={greeks?.delta_notional ?? 0}
                byUnderlying={greeks?.by_underlying ?? {}}
                shocked={replayDelta !== null}
              />
              {replayDelta !== null && (
                <p className="mt-2 px-1 text-2xs leading-relaxed text-warning">
                  Deflection is a replay of a breach, not the current book. Live
                  reading is{" "}
                  <span className="num">{greek(liveDelta)}</span> — unchanged.
                </p>
              )}
            </div>
          </Spotlight>

          {/* 2 — Telemetry grid */}
          <Spotlight active={stage.id === "TELEMETRY_GRID"}>
            <div className="space-y-3">
              <Panel title="Account" subtitle="Live from Alpaca paper">
                <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-4">
                  {[
                    ["Equity", account ? usd(account.equity) : "—"],
                    ["Day P&L", account ? usdSigned(account.day_pnl) : "—"],
                    ["Buying power", account ? usd(account.buying_power) : "—"],
                    ["Account", account?.account_number ?? "—"],
                  ].map(([label, value]) => (
                    <div key={label} className="bg-surface px-4 py-3">
                      <div className="th">{label}</div>
                      <div className="num mt-1 truncate text-sm text-foreground">
                        {value}
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
              <GreeksTelemetry
                greeks={greeks}
                volSurface={frame?.vol_surface ?? []}
                loading={!frame}
              />
              <PositionsPanel positions={frame?.positions ?? []} loading={!frame} />
            </div>
          </Spotlight>

          {/* 4 — Risk gates */}
          <Spotlight active={stage.id === "RISK_GATES"}>
            <GateInspector event={gateEvent} progress={stage.id === "RISK_GATES" ? progress : 0} />
          </Spotlight>
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {/* 3 — Reasoner */}
          <Spotlight active={stage.id === "FEATHERLESS_REASONER"}>
            <ReasonerPanel events={reasoning} />
          </Spotlight>

          {/* 5 — Hedge execution */}
          <Spotlight active={stage.id === "HEDGE_EXECUTION"}>
            <Panel
              title="Hedge execution"
              subtitle="Fractional equity orders returning exposure to neutral"
            >
              <ul className="divide-y divide-border/60">
                {hedgeEvents.length === 0 ? (
                  <li className="px-4 py-6 text-2xs text-subtle">
                    No hedge activity in the current ledger window.
                  </li>
                ) : (
                  hedgeEvents.map((e) => (
                    <li key={e.seq} className="px-4 py-2.5">
                      <div className="flex items-baseline gap-2">
                        <time className="num text-2xs text-subtle">
                          {e.ts.slice(11, 19)}
                        </time>
                        <span
                          className={cn(
                            "text-xs font-medium",
                            e.level === "warn" ? "text-warning" : "text-foreground",
                          )}
                        >
                          {e.title}
                        </span>
                      </div>
                      {e.detail && (
                        <p className="mt-0.5 text-2xs leading-relaxed text-muted">
                          {e.detail}
                        </p>
                      )}
                    </li>
                  ))
                )}
              </ul>
            </Panel>
          </Spotlight>

          <ExecutionAuditStream
            events={events}
            connected={live}
            className="min-h-[22rem] flex-1"
          />
        </div>
      </main>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Reasoner                                                                   */
/* -------------------------------------------------------------------------- */
function ReasonerPanel({ events }: { events: AuditEvent[] }) {
  const decision = [...events].reverse().find((e) => e.data?.decision);
  const d = decision?.data?.decision as
    | {
        action: string;
        symbol: string | null;
        side: string;
        contracts: number;
        confidence: number;
        thesis: string;
        source: string;
        model: string | null;
        latency_ms: number | null;
        diverged?: boolean;
        divergence?: string | null;
        baseline_symbol?: string | null;
      }
    | undefined;

  return (
    <Panel
      title="Featherless reasoner"
      subtitle="Closed-menu decision · model proposes, gates dispose"
      action={
        d?.model ? (
          <span className="num text-2xs text-subtle">{d.model}</span>
        ) : undefined
      }
    >
      {!d ? (
        <div className="flex items-center gap-2 px-4 py-8 text-2xs text-subtle">
          <Brain className="h-4 w-4" aria-hidden="true" />
          No reasoning cycle in the current ledger window.
        </div>
      ) : (
        <div className="space-y-3 px-4 py-4">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
            {[
              ["Action", d.action],
              ["Side", d.side?.toUpperCase()],
              ["Contracts", String(d.contracts)],
              ["Confidence", `${Math.round((d.confidence ?? 0) * 100)}%`],
              ["Provider", d.source],
              ["Latency", d.latency_ms ? `${d.latency_ms} ms` : "—"],
              ["Symbol", d.symbol ?? "—"],
              ["Baseline", d.baseline_symbol ?? "—"],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="th">{k}</dt>
                <dd className="num mt-1 truncate text-xs text-foreground">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="rounded-card border border-border bg-background px-3 py-2.5">
            <div className="th mb-1">Thesis</div>
            <p className="text-xs leading-relaxed text-muted">{d.thesis}</p>
          </div>

          {d.diverged && (
            <div className="rounded-card border border-warning/30 bg-warning/[0.06] px-3 py-2.5">
              <div className="flex items-center gap-1.5">
                <Radar className="h-3 w-3 text-warning" aria-hidden="true" />
                <span className="num text-2xs uppercase tracking-[0.14em] text-warning">
                  Diverged from baseline
                </span>
              </div>
              <p className="mt-1 text-2xs leading-relaxed text-muted">
                {d.divergence} — recorded, not blocked.
              </p>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/* -------------------------------------------------------------------------- */
/* Gate inspector                                                             */
/* -------------------------------------------------------------------------- */
function GateInspector({
  event,
  progress,
}: {
  event: AuditEvent | undefined;
  progress: number;
}) {
  const gate = event?.data?.gate as GateResult | undefined;
  const checks = gate?.checks ?? [];
  // Illuminate the checks in sequence across the stage.
  const revealed = Math.ceil(progress * checks.length);

  return (
    <Panel
      title="Risk gate inspector"
      subtitle={event ? event.title : "Pre-trade checks on the last evaluated order"}
      action={
        gate ? (
          <Badge tone={gate.approved ? "positive" : "negative"}>
            {gate.approved ? `${checks.length} cleared` : "vetoed"}
          </Badge>
        ) : undefined
      }
    >
      {checks.length === 0 ? (
        <div className="flex items-center gap-2 px-4 py-8 text-2xs text-subtle">
          <ShieldCheck className="h-4 w-4" aria-hidden="true" />
          No gate transcript in the current ledger window.
        </div>
      ) : (
        <ol className="divide-y divide-border/60">
          {checks.map((c, i) => {
            const on = progress === 0 || i < revealed;
            const spread = c.code.startsWith("SPREAD");
            return (
              <li
                key={`${c.code}-${i}`}
                className={cn(
                  "flex items-baseline gap-3 px-4 py-2 transition-opacity duration-300",
                  on ? "opacity-100" : "opacity-20",
                  spread && on && "bg-accent/[0.05]",
                )}
              >
                <span
                  className={cn(
                    "num w-12 shrink-0 text-2xs font-medium",
                    c.verdict === "REJECT"
                      ? "text-negative"
                      : c.verdict === "WARN"
                        ? "text-warning"
                        : "text-positive",
                  )}
                >
                  {c.verdict}
                </span>
                <span className="num w-44 shrink-0 truncate text-2xs text-subtle">
                  {c.code}
                </span>
                <span className="min-w-0 flex-1 text-2xs text-muted">{c.message}</span>
                {c.observed !== null && c.limit !== null && (
                  <span className="num shrink-0 text-2xs text-subtle">
                    {num(c.observed, 3)} / {num(c.limit, 3)}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}
