"use client";

import {
  ArrowRight,
  BadgeCheck,
  CircleAlert,
  Eye,
  EyeOff,
  KeyRound,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { AlpacaKeyGuide } from "@/components/AlpacaKeyGuide";
import { Navbar } from "@/components/Navbar";
import { Badge, Button, Field, Input, Panel, Skeleton } from "@/components/ui";
import { api, ApiError, setSessionId } from "@/lib/api";
import { cn, pct, usd } from "@/lib/format";
import type { VerifyResult } from "@/lib/types";

/** Default IV-rank bands per mandate. Mirrors Strategy.thresholds server-side. */
const STRATEGY_BANDS: Record<string, { iv_rank_sell_at: number; iv_rank_buy_at: number }> = {
  adaptive_vrp: { iv_rank_sell_at: 65, iv_rank_buy_at: 35 },
  delta_neutral_income: { iv_rank_sell_at: 60, iv_rank_buy_at: 0 },
  long_vol_convexity: { iv_rank_sell_at: 100, iv_rank_buy_at: 40 },
};

const STRATEGIES = [
  {
    id: "adaptive_vrp",
    label: "Adaptive variance risk premium",
    body: "Sells premium when IV rank is high, buys it when low, stands aside in the middle. The default.",
  },
  {
    id: "delta_neutral_income",
    label: "Delta-neutral income",
    body: "Harvests the variance risk premium by preferring short premium when volatility is rich. Needs options level 3.",
  },
  {
    id: "long_vol_convexity",
    label: "Long volatility / convexity",
    body: "Buys options when volatility is cheap relative to realised. Accepts negative theta as the cost of gamma.",
  },
];

interface EnvelopeForm {
  iv_rank_sell_at: number;
  iv_rank_buy_at: number;
  delta_drift_threshold: number;
  max_spread_pct: number;
  max_allocation_pct: number;
  max_daily_loss_pct: number;
  max_open_positions: number;
  contract_qty: number;
  min_dte: number;
  max_dte: number;
}

const DEFAULT_ENVELOPE: EnvelopeForm = {
  iv_rank_sell_at: 65,
  iv_rank_buy_at: 35,
  delta_drift_threshold: 1.0,
  max_spread_pct: 0.05,
  max_allocation_pct: 0.1,
  max_daily_loss_pct: 0.05,
  max_open_positions: 6,
  contract_qty: 1,
  min_dte: 5,
  max_dte: 60,
};

export default function OnboardingPage() {
  const router = useRouter();

  const [apiKey, setApiKey] = React.useState("");
  const [secretKey, setSecretKey] = React.useState("");
  const [showSecret, setShowSecret] = React.useState(false);

  const [verifying, setVerifying] = React.useState(false);
  const [verified, setVerified] = React.useState<VerifyResult | null>(null);
  const [verifyError, setVerifyError] = React.useState<string | null>(null);

  const [strategy, setStrategy] = React.useState("adaptive_vrp");
  const [envelope, setEnvelope] = React.useState<EnvelopeForm>(DEFAULT_ENVELOPE);

  const [launching, setLaunching] = React.useState(false);
  const [launchError, setLaunchError] = React.useState<string | null>(null);

  const verify = async (event: React.FormEvent) => {
    event.preventDefault();
    setVerifying(true);
    setVerifyError(null);
    setVerified(null);
    try {
      setVerified(await api.verify(apiKey.trim(), secretKey.trim()));
    } catch (error) {
      setVerifyError(
        error instanceof ApiError ? error.message : "Verification failed. Check your keys.",
      );
    } finally {
      setVerifying(false);
    }
  };

  const launch = async () => {
    setLaunching(true);
    setLaunchError(null);
    try {
      const result = await api.createSession({
        api_key: apiKey.trim(),
        secret_key: secretKey.trim(),
        strategy,
        ...envelope,
      });
      setSessionId(result.session_id);
      router.push("/terminal");
    } catch (error) {
      setLaunchError(
        error instanceof ApiError ? error.message : "Could not create the session.",
      );
      setLaunching(false);
    }
  };

  const setEnvelopeField = (key: keyof EnvelopeForm, value: number) =>
    setEnvelope((previous) => ({ ...previous, [key]: value }));

  const dteInvalid = envelope.min_dte >= envelope.max_dte;
  const bandInvalid = envelope.iv_rank_buy_at >= envelope.iv_rank_sell_at;
  const keysComplete = apiKey.trim().length >= 8 && secretKey.trim().length >= 8;

  return (
    <div className="min-h-screen">
      <Navbar />

      <main className="mx-auto max-w-4xl px-4 py-10 md:px-6 lg:px-8">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Connect your Alpaca paper account
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">
            Magno validates your keys against{" "}
            <code className="num text-foreground">paper-api.alpaca.markets</code>, confirms
            the account balance, and holds the credentials in memory for the life of the
            session. Nothing is written to disk.
          </p>
        </div>

        {/* Step 1 — credentials */}
        <Panel
          title="Step 1 · API credentials"
          subtitle="Paper keys only, from the Alpaca paper trading dashboard"
        >
          <form onSubmit={verify} className="space-y-4 px-4 py-4">
            <AlpacaKeyGuide />

            <Field
              label="API key ID"
              htmlFor="api-key"
              hint="Starts with PK for paper accounts."
            >
              <Input
                id="api-key"
                name="api-key"
                type="text"
                inputMode="text"
                autoComplete="username"
                spellCheck={false}
                placeholder="PK················"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="num"
                required
              />
            </Field>

            <Field
              label="Secret key"
              htmlFor="secret-key"
              hint="Sent once to validate, then held in server memory. Never logged, never persisted."
            >
              <div className="relative">
                <Input
                  id="secret-key"
                  name="secret-key"
                  type={showSecret ? "text" : "password"}
                  autoComplete="current-password"
                  spellCheck={false}
                  placeholder="••••••••••••••••••••"
                  value={secretKey}
                  onChange={(e) => setSecretKey(e.target.value)}
                  className="num pr-11"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowSecret((v) => !v)}
                  aria-label={showSecret ? "Hide secret key" : "Show secret key"}
                  className="absolute right-0 top-0 flex h-10 w-10 items-center justify-center rounded-r-control text-muted transition-colors duration-100 ease-enter hover:text-foreground"
                >
                  {showSecret ? (
                    <EyeOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Eye className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </div>
            </Field>

            {verifyError && (
              <div
                role="alert"
                className="flex gap-2 rounded-card border border-negative/40 bg-negative/5 px-3 py-2.5"
              >
                <CircleAlert
                  className="mt-0.5 h-4 w-4 shrink-0 text-negative"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-xs font-medium text-negative">Verification failed</p>
                  <p className="mt-0.5 text-2xs leading-relaxed text-muted">{verifyError}</p>
                </div>
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              loading={verifying}
              disabled={!keysComplete}
            >
              <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
              Verify account
            </Button>
          </form>
        </Panel>

        {/* Verification result */}
        {verifying && (
          <Panel title="Verifying" className="mt-4">
            <div className="grid gap-4 px-4 py-4 sm:grid-cols-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="space-y-2">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-5 w-24" />
                </div>
              ))}
            </div>
          </Panel>
        )}

        {verified && (
          <Panel
            title="Account verified"
            subtitle={verified.endpoint}
            className="mt-4 animate-fade-up"
            action={
              verified.equity_verified ? (
                <Badge tone="positive">
                  <BadgeCheck className="h-3 w-3" aria-hidden="true" />
                  {usd(verified.required_equity, 0)} baseline confirmed
                </Badge>
              ) : (
                <Badge tone="warning">Balance differs from baseline</Badge>
              )
            }
          >
            <dl className="grid grid-cols-2 gap-px border-b border-border bg-border sm:grid-cols-4">
              {[
                { label: "Equity", value: usd(verified.account.equity) },
                { label: "Buying power", value: usd(verified.account.buying_power) },
                {
                  label: "Options level",
                  value: String(verified.account.options_trading_level),
                },
                { label: "Account", value: verified.account.account_number },
              ].map((item) => (
                <div key={item.label} className="bg-surface px-4 py-3">
                  <dt className="th">{item.label}</dt>
                  <dd className="num mt-1 truncate text-sm text-foreground">{item.value}</dd>
                </div>
              ))}
            </dl>

            {verified.warnings.length > 0 && (
              <ul className="space-y-2 px-4 py-3">
                {verified.warnings.map((warning) => (
                  <li key={warning} className="flex gap-2">
                    <TriangleAlert
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning"
                      aria-hidden="true"
                    />
                    <p className="text-2xs leading-relaxed text-muted">{warning}</p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        )}

        {/* Step 2 — strategy + envelope */}
        <div
          className={cn(
            "mt-4 transition-opacity duration-200 ease-move",
            !verified && "pointer-events-none select-none opacity-40",
          )}
          aria-hidden={!verified}
        >
          <Panel
            title="Step 2 · Mandate"
            subtitle="Shapes both the model prompt and the deterministic fallback policy"
          >
            <fieldset className="space-y-2 px-4 py-4" disabled={!verified}>
              <legend className="sr-only">Agent strategy</legend>
              {STRATEGIES.map((option) => (
                <label
                  key={option.id}
                  className={cn(
                    "flex cursor-pointer gap-3 rounded-card border px-3 py-3",
                    "transition-colors duration-100 ease-enter",
                    strategy === option.id
                      ? "border-accent bg-accent/5"
                      : "border-border hover:border-border-strong hover:bg-surface-raised",
                  )}
                >
                  <input
                    type="radio"
                    name="strategy"
                    value={option.id}
                    checked={strategy === option.id}
                    onChange={() => {
                      setStrategy(option.id);
                      // Each mandate has its own natural band; adopt it as the
                      // starting point, still fully editable below.
                      const band = STRATEGY_BANDS[option.id];
                      setEnvelope((previous) => ({ ...previous, ...band }));
                    }}
                    className="mt-0.5 h-4 w-4 shrink-0 accent-accent"
                  />
                  <span className="min-w-0">
                    <span className="block text-xs font-medium text-foreground">
                      {option.label}
                    </span>
                    <span className="mt-0.5 block text-2xs leading-relaxed text-muted">
                      {option.body}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          </Panel>

          <Panel
            title="Step 3 · Risk envelope"
            subtitle="Hard limits. The agent cannot widen these at runtime."
            className="mt-4"
          >
            <fieldset
              className="grid gap-4 px-4 py-4 sm:grid-cols-2 lg:grid-cols-3"
              disabled={!verified}
            >
              <legend className="sr-only">Risk limits</legend>

              <Field
                label="Buy premium when IV rank ≤"
                htmlFor="iv-buy"
                hint="Below this percentile, options are cheap relative to how much the stock actually moves."
              >
                <Input
                  id="iv-buy"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  className="num"
                  invalid={bandInvalid}
                  value={envelope.iv_rank_buy_at}
                  onChange={(e) => setEnvelopeField("iv_rank_buy_at", Number(e.target.value))}
                />
              </Field>

              <Field
                label="Sell premium when IV rank ≥"
                htmlFor="iv-sell"
                error={bandInvalid ? "Sell threshold must sit above the buy threshold." : undefined}
                hint="Above this percentile, options are expensive and selling is the edge."
              >
                <Input
                  id="iv-sell"
                  type="number"
                  min={0}
                  max={100}
                  step={1}
                  className="num"
                  invalid={bandInvalid}
                  value={envelope.iv_rank_sell_at}
                  onChange={(e) => setEnvelopeField("iv_rank_sell_at", Number(e.target.value))}
                />
              </Field>

              <Field
                label="Delta drift cap"
                htmlFor="drift"
                hint="Hedge fires once |net Δ| reaches this."
              >
                <Input
                  id="drift"
                  type="number"
                  min={0.05}
                  max={100}
                  step={0.05}
                  className="num"
                  value={envelope.delta_drift_threshold}
                  onChange={(e) =>
                    setEnvelopeField("delta_drift_threshold", Number(e.target.value))
                  }
                />
              </Field>

              <Field
                label="Max bid/ask spread"
                htmlFor="spread"
                hint={`Rejects wider than ${pct(envelope.max_spread_pct)} of mid.`}
              >
                <Input
                  id="spread"
                  type="number"
                  min={0.005}
                  max={0.5}
                  step={0.005}
                  className="num"
                  value={envelope.max_spread_pct}
                  onChange={(e) => setEnvelopeField("max_spread_pct", Number(e.target.value))}
                />
              </Field>

              <Field
                label="Max allocation"
                htmlFor="allocation"
                hint={`${pct(envelope.max_allocation_pct, 0)} of buying power per trade.`}
              >
                <Input
                  id="allocation"
                  type="number"
                  min={0.01}
                  max={1}
                  step={0.01}
                  className="num"
                  value={envelope.max_allocation_pct}
                  onChange={(e) =>
                    setEnvelopeField("max_allocation_pct", Number(e.target.value))
                  }
                />
              </Field>

              <Field
                label="Daily loss breaker"
                htmlFor="loss"
                hint={`Stops new risk at ${pct(envelope.max_daily_loss_pct, 0)} drawdown. Hedging continues.`}
              >
                <Input
                  id="loss"
                  type="number"
                  min={0.01}
                  max={1}
                  step={0.01}
                  className="num"
                  value={envelope.max_daily_loss_pct}
                  onChange={(e) =>
                    setEnvelopeField("max_daily_loss_pct", Number(e.target.value))
                  }
                />
              </Field>

              <Field
                label="Max open positions"
                htmlFor="positions"
                hint="Concentration cap across the book."
              >
                <Input
                  id="positions"
                  type="number"
                  min={1}
                  max={50}
                  step={1}
                  className="num"
                  value={envelope.max_open_positions}
                  onChange={(e) =>
                    setEnvelopeField("max_open_positions", Number(e.target.value))
                  }
                />
              </Field>

              <Field
                label="Contracts per trade"
                htmlFor="qty"
                hint="Upper bound on what the model may size."
              >
                <Input
                  id="qty"
                  type="number"
                  min={1}
                  max={50}
                  step={1}
                  className="num"
                  value={envelope.contract_qty}
                  onChange={(e) => setEnvelopeField("contract_qty", Number(e.target.value))}
                />
              </Field>

              <Field
                label="Min days to expiry"
                htmlFor="min-dte"
                error={dteInvalid ? "Must be below the maximum." : undefined}
                hint="Below this, pin and gamma risk dominate."
              >
                <Input
                  id="min-dte"
                  type="number"
                  min={0}
                  max={400}
                  step={1}
                  className="num"
                  invalid={dteInvalid}
                  value={envelope.min_dte}
                  onChange={(e) => setEnvelopeField("min_dte", Number(e.target.value))}
                />
              </Field>

              <Field
                label="Max days to expiry"
                htmlFor="max-dte"
                hint="Above this, capital efficiency falls away."
              >
                <Input
                  id="max-dte"
                  type="number"
                  min={1}
                  max={800}
                  step={1}
                  className="num"
                  invalid={dteInvalid}
                  value={envelope.max_dte}
                  onChange={(e) => setEnvelopeField("max_dte", Number(e.target.value))}
                />
              </Field>
            </fieldset>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
              <p className="flex items-center gap-1.5 text-2xs text-subtle">
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                Autopilot starts disarmed. You engage it from the terminal.
              </p>
              <Button
                variant="primary"
                onClick={launch}
                loading={launching}
                disabled={!verified || dteInvalid || bandInvalid}
              >
                Launch terminal
                <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Button>
            </div>

            {launchError && (
              <div
                role="alert"
                className="mx-4 mb-4 flex gap-2 rounded-card border border-negative/40 bg-negative/5 px-3 py-2.5"
              >
                <CircleAlert
                  className="mt-0.5 h-4 w-4 shrink-0 text-negative"
                  aria-hidden="true"
                />
                <div>
                  <p className="text-xs font-medium text-negative">Could not start</p>
                  <p className="mt-0.5 text-2xs leading-relaxed text-muted">{launchError}</p>
                </div>
              </div>
            )}
          </Panel>
        </div>

        <p className="mt-6 text-2xs leading-relaxed text-subtle">
          No paper account yet?{" "}
          <a
            href="https://app.alpaca.markets/paper/dashboard/overview"
            target="_blank"
            rel="noreferrer noopener"
            className="text-accent-bright underline-offset-2 hover:underline"
          >
            Create one at Alpaca
          </a>
          {" "}and generate paper keys — options are already enabled at level 3 on paper
          accounts. Already connected?{" "}
          <Link href="/terminal" className="text-accent-bright underline-offset-2 hover:underline">
            Go to the terminal
          </Link>
          .
        </p>
      </main>
    </div>
  );
}
